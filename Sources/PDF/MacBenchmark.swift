import AppKit
import PDFKit
import CryptoKit
import Darwin

struct BenchmarkMetric: Codable, Identifiable, Sendable {
    let id:String
    let name:String
    let samplesMilliseconds:[Double]
    let detail:String
    let error:String?
    var medianMilliseconds:Double? {
        let sorted = samplesMilliseconds.sorted()
        guard !sorted.isEmpty else { return nil }
        return sorted.count % 2 == 0 ? (sorted[sorted.count/2-1]+sorted[sorted.count/2])/2 : sorted[sorted.count/2]
    }
}

struct BenchmarkReport: Codable, Sendable {
    let schemaVersion:Int
    let createdAt:Date
    let applicationVersion:String
    let processor:String
    let virtualization:String
    let architecture:String
    let operatingSystem:String
    let graphicsDevice:String
    let activeProcessorCount:Int
    let physicalMemoryBytes:UInt64
    let processPeakMemoryBytes:UInt64
    let sourceName:String
    let sourceSHA256:String
    let sourceBytes:Int
    let pageCount:Int
    let fixture:String?
    let repetitions:Int
    let metrics:[BenchmarkMetric]
    let methodology:String
    var processorIdentifiesM4OrLater:Bool {
        guard let range = processor.range(of:"Apple M[0-9]+",options:.regularExpression),
              let generation = Int(processor[range].dropFirst(7)) else { return false }
        return generation >= 4
    }
}

@MainActor enum MacBenchmark {
    static func run(input:URL?,output:URL,pages:Int = 100) throws {
        // In-app runs place the report inside a parent-managed private job
        // directory. Its parent process can remove all copies even after SIGTERM.
        let report = try measure(input:input,pages:pages,workDirectory:output.deletingLastPathComponent())
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted,.sortedKeys]; encoder.dateEncodingStrategy = .iso8601
        try NativeOutput.write(encoder.encode(report),to:output)
        print("PDF benchmark saved: \(report.pageCount) pages; \(report.processor); processor identifies M4+=\(report.processorIdentifiesM4OrLater); \(report.virtualization)")
    }

    static func measure(input:URL?,pages:Int = 100,repetitions:Int = 3,includeOCR:Bool = true,workDirectory:URL? = nil) throws -> BenchmarkReport {
        guard (1...2000).contains(pages),(1...10).contains(repetitions) else { throw failure("Escolha entre 1 e 2.000 páginas e entre 1 e 10 repetições.") }
        let folder = (workDirectory ?? FileManager.default.temporaryDirectory).appendingPathComponent("PDF-benchmark-" + UUID().uuidString,isDirectory:true)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        defer { try? FileManager.default.removeItem(at:folder) }
        let source:URL
        if let input {
            let attributes = try input.resourceValues(forKeys:[.isRegularFileKey,.fileSizeKey])
            guard attributes.isRegularFile == true,(attributes.fileSize ?? Int.max) <= 1_073_741_824 else { throw failure("O benchmark aceita arquivos PDF regulares de até 1 GB.") }
            source = folder.appendingPathComponent("benchmark-input.pdf")
            try NativeOutput.write(Data(contentsOf:input),to:source)
        }
        else { source = folder.appendingPathComponent("PDF-benchmark-v1.pdf"); try fixture(pages:pages,to:source) }
        guard let document = PDFDocument(url:source),!document.isLocked,document.pageCount > 0 else { throw failure("Escolha um PDF legível e desbloqueado, ou use o documento de amostra.") }
        let data = try Data(contentsOf:source,options:.mappedIfSafe)
        let hash = SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined()
        var metrics:[BenchmarkMetric] = []
        func record(_ id:String,_ name:String,_ detail:String,_ body:() throws -> Void) {
            var durations:[Double] = []
            do {
                // Warm the requested operation once; the report does not call
                // these results cold-cache or compare them to another machine.
                try autoreleasepool(invoking:body)
                for _ in 0..<repetitions {
                    let start = DispatchTime.now().uptimeNanoseconds
                    try autoreleasepool(invoking:body)
                    durations.append(Double(DispatchTime.now().uptimeNanoseconds-start)/1_000_000)
                }
                metrics.append(BenchmarkMetric(id:id,name:name,samplesMilliseconds:durations,detail:detail,error:nil))
            } catch {
                metrics.append(BenchmarkMetric(id:id,name:name,samplesMilliseconds:durations,detail:detail,error:error.localizedDescription))
            }
        }
        record("open","Abrir documento","Abrir o arquivo e resolver primeira e última página; cache do sistema preservado.") {
            guard let opened = PDFDocument(url:source),opened.pageCount == document.pageCount,
                  opened.page(at:0) != nil,opened.page(at:opened.pageCount-1) != nil else { throw failure("Abertura ou acesso às páginas falhou.") }
        }
        record("extract","Extrair texto","Percorrer o texto de todas as páginas.") {
            let text = document.string ?? ""
            if input == nil, !text.contains("página \(pages)") { throw failure("A extração não recuperou o conteúdo conhecido da última página da amostra.") }
        }
        let matches = document.findString("benchmark",withOptions:.caseInsensitive).count
        record("search","Buscar no documento","Termo fixo: benchmark; \(matches) ocorrências na amostra selecionada.") {
            let count = document.findString("benchmark",withOptions:.caseInsensitive).count
            if input == nil, count != pages { throw failure("A busca não encontrou o termo conhecido em todas as páginas da amostra.") }
        }
        let indexes = Array(Set([0,document.pageCount/2,document.pageCount-1])).sorted()
        record("render","Renderizar páginas","Primeira, central e última página; miniatura de até 1.200 × 1.600 pontos.") {
            for index in indexes {
                guard let page = document.page(at:index) else { throw failure("Página indisponível.") }
                let thumbnail = page.thumbnail(of:NSSize(width:1200,height:1600),for:.cropBox)
                guard thumbnail.cgImage(forProposedRect:nil,context:nil,hints:nil) != nil else { throw failure("Renderização indisponível.") }
            }
        }
        if let first = document.page(at:0) {
            let raster = first.thumbnail(of:NSSize(width:1200,height:1600),for:.cropBox)
            if let image = raster.cgImage(forProposedRect:nil,context:nil,hints:nil) {
                record("contrast","Processar imagem","Core Image com contexto Metal quando disponível; mesma primeira página.") {
                    let enhanced = try GPUImageProcessor.enhance(image)
                    guard enhanced.width == image.width,enhanced.height == image.height else { throw failure("O processamento alterou as dimensões.") }
                }
                if includeOCR {
                    record("ocr","Reconhecer texto","Vision preciso na primeira página, inglês. O tempo inclui tentativas, lançamento e comunicação com processo isolado quando necessário. A memória medida é do processo principal; não soma o pico do filho.") {
                        let observations = try VisionRecognition.recognize(image,language:"en",cancellation:NativeCancellation())
                        if input == nil, !observations.contains(where:{ $0.string.localizedCaseInsensitiveContains("benchmark") }) {
                            throw failure("O OCR não reconheceu o texto conhecido da amostra.")
                        }
                    }
                }
            }
        }
        var usage = rusage()
        let peak = getrusage(RUSAGE_SELF,&usage) == 0 ? UInt64(max(0,usage.ru_maxrss)) : 0
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "other"
        #endif
        return BenchmarkReport(schemaVersion:1,createdAt:Date(),applicationVersion:Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? "development",
                               processor:processorName(),virtualization:virtualizationStatus(),architecture:architecture,operatingSystem:ProcessInfo.processInfo.operatingSystemVersionString,
                               graphicsDevice:AppleHardware.graphicsDevice,activeProcessorCount:ProcessInfo.processInfo.activeProcessorCount,
                               physicalMemoryBytes:ProcessInfo.processInfo.physicalMemory,processPeakMemoryBytes:peak,
                               sourceName:input?.lastPathComponent ?? "Amostra sintética PDF v1",sourceSHA256:hash,sourceBytes:data.count,pageCount:document.pageCount,
                               fixture:input == nil ? "text-and-vector-v1" : nil,repetitions:repetitions,metrics:metrics,
                               methodology:"Processo dedicado pelo aplicativo; arquivo de entrada copiado para pasta privada e removido ao terminar; uma execução de aquecimento e repetições sequenciais. Não limpa caches. Pico de RSS inclui geração/leitura da amostra, aquecimento e todas as operações. A amostra sintética contém texto e vetores; use o mesmo arquivo e SHA-256 para comparações entre Macs. O nome da GPU identifica disponibilidade, não mede ocupação nem uso do Neural Engine. Erros de uma operação são registrados, não convertidos em tempos zero.")
    }
    static func processorName() -> String {
        systemString("machdep.cpu.brand_string") ?? "Processador não identificado"
    }
    private static func systemString(_ key:String) -> String? {
        var size = 0
        guard sysctlbyname(key,nil,&size,nil,0) == 0,size > 0 else { return nil }
        var bytes = [UInt8](repeating:0,count:size)
        let result = bytes.withUnsafeMutableBytes { sysctlbyname(key,$0.baseAddress,&size,nil,0) }
        return result == 0 ? String(decoding:bytes.prefix(while:{$0 != 0}),as:UTF8.self) : nil
    }
    private static func virtualizationStatus() -> String {
        var flag:Int32 = 0, size = MemoryLayout<Int32>.size
        let detected = sysctlbyname("kern.hv_vmm_present",&flag,&size,nil,0) == 0 && flag != 0
        if detected || processorName().localizedCaseInsensitiveContains("virtual") || (systemString("hw.model") ?? "").localizedCaseInsensitiveContains("virtual") { return "Virtualização detectada nos indicadores do sistema." }
        return "Virtualização não detectada pelos indicadores disponíveis; isso não certifica execução em hardware físico."
    }
    static func fixture(pages:Int,to destination:URL) throws {
        var bounds = CGRect(x:0,y:0,width:595,height:842)
        guard let context = CGContext(destination as CFURL,mediaBox:&bounds,nil) else { throw failure("Não foi possível preparar a amostra.") }
        for page in 1...pages {
            context.beginPDFPage(nil)
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(cgContext:context,flipped:false)
            ("PDF benchmark · página \(page)" as NSString).draw(at:NSPoint(x:42,y:775),withAttributes:[.font:NSFont.systemFont(ofSize:22,weight:.semibold),.foregroundColor:NSColor.systemBlue])
            for row in 0..<25 {
                ("Document reading, search and rendering sample — row \(row+1)." as NSString).draw(at:NSPoint(x:42,y:CGFloat(725-row*22)),withAttributes:[.font:NSFont.systemFont(ofSize:12),.foregroundColor:NSColor.black])
            }
            context.setFillColor(NSColor.systemBlue.cgColor)
            context.fill(CGRect(x:42,y:80,width:CGFloat(180+page%150),height:28))
            NSGraphicsContext.restoreGraphicsState()
            context.endPDFPage()
        }
        context.closePDF()
    }
    private static func failure(_ message:String) -> NSError { NSError(domain:"PDF.Benchmark",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
}

@MainActor enum BenchmarkAuditChecks {
    static func run() throws {
        let report = try MacBenchmark.measure(input:nil,pages:4,repetitions:2,includeOCR:false)
        guard report.pageCount == 4,report.sourceBytes > 0,report.sourceSHA256.count == 64,
              report.metrics.count == 5,report.metrics.allSatisfy({ $0.error == nil && $0.samplesMilliseconds.count == 2 && $0.samplesMilliseconds.allSatisfy({ $0.isFinite && $0 >= 0 }) }) else {
            throw NSError(domain:"PDF.BenchmarkAudit",code:1,userInfo:[NSLocalizedDescriptionKey:"O benchmark não executou medições válidas das operações esperadas."])
        }
        let encoder = JSONEncoder(); let decoded = try JSONDecoder().decode(BenchmarkReport.self,from:encoder.encode(report))
        guard decoded.sourceSHA256 == report.sourceSHA256, decoded.metrics.count == report.metrics.count else { throw RecoveryError.invalidRecord }
        print("Benchmark harness audit passed; processor: \(report.processor); \(report.virtualization)")
    }
}
