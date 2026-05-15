# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 빌드 설정
# 실행: pyinstaller aunion.spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 숨겨진 임포트 (PyInstaller가 자동 감지 못하는 것들)
hiddenimports = [
    # uvicorn
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.loops.uvloop',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    # fastapi + starlette
    'fastapi',
    'starlette',
    'starlette.applications',
    'starlette.middleware',
    'starlette.middleware.cors',
    'starlette.routing',
    'starlette.requests',
    'starlette.responses',
    'starlette.websockets',
    'starlette.staticfiles',
    'starlette.background',
    'starlette.concurrency',
    'starlette.datastructures',
    'starlette.exceptions',
    'starlette.formparsers',
    'starlette.templating',
    'starlette.testclient',
    'starlette.types',
    'anyio',
    'anyio._backends._asyncio',
    'anyio._backends._trio',
    'h11',
    # AI/ML Core
    'transformers',
    'torch',
    'numpy',
    'soundfile',
    # ASR - openai/whisper-large-v3-turbo (CTranslate2 int8 변환본)
    'accelerate',
    # NMT-ASR - facebook/nllb-200-distilled-600M (CTranslate2 CT2 우선, HF 폴백)
    'sentencepiece',
    'PIL',
    # Slide OCR + VLM (Surya OCR + Qwen2.5-VL 번역)
    'bitsandbytes',
    # 프로젝트 루트의 슬라이드 번역 모듈 (run.py가 sys.path에 root 추가하면 import됨)
    'translate_slide_v3',
]

hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('transformers')
hiddenimports += collect_submodules('torch')
# Surya OCR — image_pipeline.stage_ocr_surya 가 lazy import 라 정적 분석이 자동 감지 못함.
# 누락 시 이미지/스캔 PDF 의 OCR 단계에서 ImportError → 번역이 silent fail (원본만 학생에게 표시).
# pdftext 등 surya 의존성은 PyInstaller 가 surya 분석 시 자동 추적함.
hiddenimports += collect_submodules('surya')

# 데이터 파일
datas = []
datas += collect_data_files('transformers')
# faster_whisper의 assets/silero_vad_v6.onnx — vad_filter=True 사용 시 필수
datas += collect_data_files('faster_whisper')
# Surya — tokenizer · processor 메타데이터 동봉. (실제 OCR 모델 weight 는 첫 호출 시 HF 캐시에 다운로드)
datas += collect_data_files('surya')

# 앱 디렉토리 포함
datas += [
    ('app', 'app'),
    # 수강생 브라우저 접속용 프론트엔드 빌드 결과물
    ('../frontend/dist', 'frontend_dist'),
]

a = Analysis(
    ['run.py'],
    pathex=['.', '..'],  # '..' = project root → translate_slide_v3.py 등 root 모듈 검색 가능
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='aunion_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 백그라운드 실행 시 False로 변경
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='aunion_backend',
)
