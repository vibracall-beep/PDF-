"""Typed workflow execution, with atomic all-or-nothing batch publication.

The outer pdf_engine.run owns final publication. This module writes only inside
its private staging directory; it never publishes a partial batch itself.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

TERMINAL_OUTPUTS = {
    "word": ("docx", False), "excel": ("xlsx", False),
    "powerpoint": ("pptx", False), "markdown": ("md", False),
    "jpg": ("", True), "png": ("", True), "split": ("", True),
    "forms": ("json", False), "form-detect": ("json", False),
    "layout-extract": ("json", False), "compare": ("txt", False),
    "compare-visual": ("html", False),
    "verify-signatures": ("json", False), "validate-pdfa": ("json", False),
    "validate-pdfua": ("json", False), "ocr-page": ("json", False),
}
SOURCE_CONVERTERS = {"office", "odt", "rtf", "txt", "epub", "csv", "html", "images", "ocr-page"}
MULTI_SOURCE = {"merge", "images", "compare", "compare-visual"}


def output_type(operation, options=None):
    if operation == "jpg" and (options or {}).get("format") == "png":
        operation = "png"
    return TERMINAL_OUTPUTS.get(operation, ("pdf", False))


def validate_steps(steps, tools, pdf_operations, *, batch=False):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
        raise ValueError("O fluxo precisa de 1 a 64 etapas.")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("operation"), str) or step.get("operation") not in tools or step["operation"] == "workflow":
            raise ValueError(f"Etapa {index + 1} inválida; fluxos recursivos não são permitidos.")
        operation = step["operation"]
        if not isinstance(step.get("options", {}), dict):
            raise ValueError(f"As opções da etapa {index + 1} devem ser um objeto JSON.")
        if index < len(steps) - 1 and operation == "digital-sign":
            raise ValueError("A assinatura digital deve ser a última etapa; modificações posteriores invalidam a assinatura.")
        if index < len(steps) - 1 and operation not in pdf_operations:
            raise ValueError("Uma exportação deve ser a última etapa; etapas intermediárias precisam produzir um PDF único.")
        if index > 0 and operation in SOURCE_CONVERTERS | MULTI_SOURCE:
            raise ValueError(f"{operation}: esta operação de entrada só pode ser a primeira etapa do fluxo.")
        if batch and operation in SOURCE_CONVERTERS | MULTI_SOURCE:
            raise ValueError(f"{operation} não aceita um lote independente de PDFs neste fluxo.")
    return steps


def check_dependencies(steps):
    """Fail before processing any file when a known converter is unavailable."""
    modules = {"word": "docx", "excel": "openpyxl", "powerpoint": "pptx"}
    for step in steps:
        operation = step["operation"]
        module = modules.get(operation)
        if module and importlib.util.find_spec(module) is None:
            raise ValueError(f"A etapa {operation} requer o módulo {module}. Execute o instalador completo.")
        if operation in ("ocr", "pdfa") and not shutil.which("ocrmypdf"):
            raise ValueError("O fluxo requer OCRmyPDF instalado e os idiomas de OCR selecionados.")
        if operation in ("office", "odt", "rtf", "csv") and not (shutil.which("soffice") or Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").is_file()):
            raise ValueError("O fluxo requer LibreOffice instalado.")
        if operation == "html" and importlib.util.find_spec("playwright") is None:
            raise ValueError("A conversão HTML requer Playwright e Chromium instalados.")


def result_name(source, index, operation, options=None):
    # Numeric prefixes remain unique even on case-insensitive/normalizing volumes.
    stem = unicodedata.normalize("NFC", Path(source).stem)
    stem = "".join(c for c in stem if unicodedata.category(c)[0] != "C")
    stem = re.sub(r'[/:\\<>|?*"\x00]', "-", stem).strip(" .") or "Documento"
    stem = stem.encode("utf-8")[:160].decode("utf-8", errors="ignore").rstrip(" .") or "Documento"
    suffix, _ = output_type(operation, options)
    return f"{index + 1:04d}-{stem}" + (f".{suffix}" if suffix else "")


def execute(inputs, output, options, *, run, tools, pdf_operations, progress=None):
    raw_batch = options.get("batch", False)
    if not isinstance(raw_batch, bool):
        raise ValueError("batch deve ser true ou false.")
    batch = raw_batch
    steps = validate_steps(options.get("steps", []), tools, pdf_operations, batch=batch)
    if batch and len(inputs) > 1000:
        raise ValueError("Use no máximo 1.000 PDFs por lote.")
    credentials = options.get("input_passwords")
    if credentials is not None and (not isinstance(credentials, list) or len(credentials) != len(inputs) or any(not isinstance(value, str) for value in credentials)):
        raise ValueError("input_passwords deve conter uma senha por arquivo de entrada.")
    if credentials is not None and not batch:
        raise ValueError("Use input_passwords no lote; um fluxo único usa password ou as opções da primeira etapa.")
    password = options.get("password", "")
    if not isinstance(password, str):
        raise ValueError("A senha deve ser uma string.")
    check_dependencies(steps)
    final = steps[-1]
    jobs = [[source] for source in inputs] if batch else [inputs]
    total = len(jobs) * len(steps)
    completed = 0
    output = Path(output)
    if batch:
        output.mkdir(mode=0o700)
    results = []

    def report(file_index, stage_index):
        event = dict(event="workflow_progress", completed=completed, total=total,
                     file_index=file_index + 1, file_total=len(jobs),
                     stage_index=stage_index + 1, stage_total=len(steps))
        if progress is not None:
            progress(event)
        if options.get("progress") is True:
            print(json.dumps(event), flush=True)

    for file_index, sources in enumerate(jobs):
        current = sources
        current_password = credentials[file_index] if credentials is not None else password
        target_name = result_name(sources[0], file_index, final["operation"], final.get("options")) if batch else output.name
        destination = output / target_name if batch else output
        stage_index = 0
        try:
            with tempfile.TemporaryDirectory(prefix=".workflow-", dir=output.parent) as temporary:
                for stage_index, step in enumerate(steps):
                    report(file_index, stage_index)
                    target = destination if stage_index == len(steps) - 1 else Path(temporary) / f"{stage_index}.pdf"
                    settings = dict(step.get("options", {}))
                    if current_password and "password" not in settings:
                        settings["password"] = current_password
                    run(step["operation"], current, target, settings)
                    current_password = settings.get("output_password", settings.get("password", current_password))
                    if step["operation"] in ("merge", "organize") and not current_password:
                        current_password = next((value for value in settings.get("input_passwords", []) if value), "")
                    if step["operation"] == "protect":
                        current_password = settings.get("new_password", "")
                    if step["operation"] == "unlock":
                        current_password = ""
                    current = [str(target)]
                    completed += 1
                    report(file_index, stage_index)
        except Exception as error:
            if not batch:
                raise
            raise ValueError(f"Lote interrompido no arquivo {file_index + 1}/{len(jobs)}, etapa {stage_index + 1}: {error}. Nenhum resultado do lote foi publicado.") from error
        results.append(dict(index=file_index + 1, output=target_name, status="completed"))
    if batch:
        # Never persist options, source paths or passwords in the result manifest.
        manifest = dict(version=1, atomic=True, count=len(results), results=results)
        (output / "batch-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
