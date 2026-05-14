// onnxruntime-web 전역(ort.all.min.js) 설정 — VAD(@ricky0123/vad-web)가 쓰는 ORT 런타임을
// 단일 스레드로 고정. index.html 의 defer 스크립트로 ort.all.min.js 직후 실행됨.
window.ort.env.wasm.numThreads = 1;
