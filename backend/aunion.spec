# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 빌드 설정
# 실행: pyinstaller aunion.spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

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
    # Slide OCR + VLM (Surya OCR + Qwen3-VL-4B 번역)
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
# transformers/audio_utils.py 가 import 시점에 importlib.metadata.version("torchcodec") 호출.
# venv 에 torchcodec 설치돼 있어 PyInstaller 가 find_spec 통과시키지만 .dist-info 메타는 누락 →
# PackageNotFoundError 로 surya import 전체 fail. 우리는 torchcodec 자체는 안 쓰지만 (오디오는
# soundfile/librosa 경로), transitive metadata 만 동봉해 if 분기를 정상 통과시킴.
datas += copy_metadata('torchcodec')

# 앱 디렉토리 포함
# frontend/dist 존재 가드 — PyInstaller 가 stale/없는 dist 를 그대로 번들해서
# setup.exe 안에 옛 프론트가 박히는 사고 방지 (사건 재발 방지).
# PyInstaller spec namespace 에 __file__ 없음. SPECPATH (PyInstaller 가 주입하는 글로벌)
# 를 써서 spec 파일이 어디서 실행되든 안정적으로 frontend/dist 위치 찾음.
import os as _os
_check_paths = [
    _os.path.join(SPECPATH, '..', 'frontend', 'dist', 'index.html'),  # SPECPATH 기반 (정석)
    _os.path.abspath('../frontend/dist/index.html'),                  # backend/ cwd 가정
    _os.path.abspath('frontend/dist/index.html'),                     # 프로젝트 루트 cwd 가정
]
if not any(_os.path.exists(p) for p in _check_paths):
    raise SystemExit(
        'frontend/dist/index.html 이 없습니다. '
        '먼저 `npm run build --prefix frontend` 로 프론트엔드를 빌드하세요.\n'
        '확인한 경로: ' + ', '.join(_check_paths)
    )

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
