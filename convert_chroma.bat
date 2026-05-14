@echo off
setlocal

REM === 공통 설정 ===
REM 크로마키 색상 (녹색)
set CHROMA_COLOR=0x00FF00

    REM 유사도 (0.01-1.0). 적절한 크로마키 유사도 설정.
    set SIMILARITY=0.15

    REM 경계 부드러움 (0.0-1.0). 가장자리 찌꺼기를 부드럽게 지워줍니다.
    set BLEND=0.05

REM === 파일 설정 ===
set INPUT_1=frontend\public\chroma_source_white.mp4
set OUTPUT_1=frontend\public\animation_white.webm

set INPUT_2=frontend\public\chroma_source_black.mp4
set OUTPUT_2=frontend\public\animation_black.webm

REM === 실행: 첫 번째 영상 변환 ===
if exist "%INPUT_1%" (
    echo.
    echo [FFmpeg] 영상 변환을 시작합니다: %INPUT_1%
    echo   - 출력: %OUTPUT_1%
    echo.

    REM 투명 배경 애니메이션의 잔상(Ghosting) 문제를 피하기 위해 WebM(VP9) 포맷 사용
    REM despill=green 필터를 추가하여 캐릭터 가장자리에 남는 초록색 반사광(스필) 현상을 제거합니다.
    ffmpeg -y -i "%INPUT_1%" -vf "chromakey=%CHROMA_COLOR%:%SIMILARITY%:%BLEND%,despill=green,format=yuva420p" -c:v libvpx-vp9 -b:v 0 -crf 30 -auto-alt-ref 0 -an "%OUTPUT_1%"

    if %errorlevel% equ 0 (
        echo.
        echo [성공] 변환이 완료되었습니다: %OUTPUT_1%
    ) else (
        echo.
        echo [오류] 변환 중 오류가 발생했습니다.
    )
) else (
    echo.
    echo [정보] 입력 파일이 없습니다: %INPUT_1%
)

echo.
echo ==================================================
echo.

REM === 실행: 두 번째 영상 변환 ===
if exist "%INPUT_2%" (
    echo.
    echo [FFmpeg] 영상 변환을 시작합니다: %INPUT_2%
    echo   - 출력: %OUTPUT_2%
    echo.

    ffmpeg -y -i "%INPUT_2%" -vf "chromakey=%CHROMA_COLOR%:%SIMILARITY%:%BLEND%,despill=green,format=yuva420p" -c:v libvpx-vp9 -b:v 0 -crf 30 -auto-alt-ref 0 -an "%OUTPUT_2%"

    if %errorlevel% equ 0 (
        echo.
        echo [성공] 변환이 완료되었습니다: %OUTPUT_2%
    ) else (
        echo.
        echo [오류] 변환 중 오류가 발생했습니다.
    )
) else (
    echo.
    echo [정보] 입력 파일이 없습니다: %INPUT_2%
)

endlocal