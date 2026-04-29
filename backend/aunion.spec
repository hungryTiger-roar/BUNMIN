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
    # ASR - ghost613/faster-whisper-large-v3-turbo-korean (CTranslate2)
    'accelerate',
    # NMT-ASR - Helsinki-NLP/opus-mt-ko-en (CTranslate2 CT2 우선, HF 폴백)
    'sentencepiece',
    # OCR - RapidOCR + Korean PP-OCRv4
    'rapidocr_onnxruntime',
    'PIL',
    # Slide VLM (EasyOCR + Qwen3-VL + LoRA)
    'easyocr',
    'peft',
    'bitsandbytes',
]

hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('transformers')
hiddenimports += collect_submodules('torch')

# 데이터 파일
datas = []
datas += collect_data_files('transformers')
datas += collect_data_files('rapidocr_onnxruntime')

# 앱 디렉토리 포함
datas += [
    ('app', 'app'),
    # 수강생 브라우저 접속용 프론트엔드 빌드 결과물
    ('../frontend/dist', 'frontend_dist'),
]

a = Analysis(
    ['run.py'],
    pathex=['.'],
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
