"""
평가용 샘플 데이터 자동 생성 스크립트

OCR: Pillow로 슬라이드 형태 PNG 이미지 생성

사용법:
    python evaluation/generate_samples.py
"""
import json
import argparse
from pathlib import Path

OCR_DIR = Path(__file__).parent / "datasets" / "ocr_samples"

# ──────────────────────────────────────────────
# OCR 샘플 데이터 정의
# ──────────────────────────────────────────────
OCR_SAMPLES = [
    {
        "file": "sample_01.png",
        "text": "머신러닝의 기본 개념과 응용",
        "subtitle": "지도학습, 비지도학습, 강화학습",
        "body": ["1. 지도학습: 레이블된 데이터로 학습", "2. 비지도학습: 레이블 없이 패턴 발견", "3. 강화학습: 보상을 통한 최적 행동 학습"],
    },
    {
        "file": "sample_02.png",
        "text": "딥러닝 신경망 구조",
        "subtitle": "입력층, 은닉층, 출력층",
        "body": ["- 입력층: 원시 데이터 수신", "- 은닉층: 특성 추출 및 변환", "- 출력층: 최종 예측 결과 출력"],
    },
    {
        "file": "sample_03.png",
        "text": "데이터 전처리 방법",
        "subtitle": "정규화, 표준화, 결측치 처리",
        "body": ["정규화: 값을 0~1 범위로 변환", "표준화: 평균 0, 분산 1로 변환", "결측치: 평균값 또는 중앙값으로 대체"],
    },
    {
        "file": "sample_04.png",
        "text": "모델 평가 지표",
        "subtitle": "정확도, 정밀도, 재현율, F1 Score",
        "body": ["정확도 = (TP + TN) / 전체", "정밀도 = TP / (TP + FP)", "재현율 = TP / (TP + FN)", "F1 = 2 * (정밀도 * 재현율) / (정밀도 + 재현율)"],
    },
    {
        "file": "sample_05.png",
        "text": "과적합 방지 기법",
        "subtitle": "드롭아웃, 정규화, 데이터 증강",
        "body": ["드롭아웃: 훈련 중 일부 뉴런 비활성화", "L2 정규화: 가중치 크기에 패널티 부여", "데이터 증강: 학습 데이터 인위적으로 확장"],
    },
    {
        "file": "sample_06.png",
        "text": "트랜스포머 아키텍처",
        "subtitle": "인코더-디코더 구조",
        "body": ["멀티헤드 어텐션: 다양한 관점에서 정보 통합", "포지셔널 인코딩: 단어 위치 정보 추가", "피드포워드 네트워크: 비선형 변환 수행"],
    },
    {
        "file": "sample_07.png",
        "text": "자연어 처리 파이프라인",
        "subtitle": "텍스트 전처리부터 모델 출력까지",
        "body": ["1단계: 토크나이징 및 정제", "2단계: 임베딩 변환", "3단계: 모델 추론 및 디코딩"],
    },
    {
        "file": "sample_08.png",
        "text": "실시간 번역 시스템 구조",
        "subtitle": "ASR - MT - TTS 파이프라인",
        "body": ["ASR: 음성 입력을 텍스트로 변환", "MT: 한국어 텍스트를 영어로 번역", "TTS: 번역된 텍스트를 음성으로 합성"],
    },
    {
        "file": "sample_09.png",
        "text": "최적화 알고리즘 비교",
        "subtitle": "SGD, Adam, AdamW",
        "body": ["SGD: 기본 경사 하강법, 안정적", "Adam: 적응적 학습률, 빠른 수렴", "AdamW: 가중치 감쇠 추가, 일반화 향상"],
    },
    {
        "file": "sample_10.png",
        "text": "모델 압축 기법",
        "subtitle": "경량화를 통한 실시간 추론",
        "body": ["지식 증류: 큰 모델의 지식을 소형 모델에 전달", "양자화: 부동소수점을 정수로 변환", "가지치기: 불필요한 가중치 제거"],
    },
    {
        "file": "sample_11.png",
        "text": "OCR 기술 소개",
        "subtitle": "광학 문자 인식 원리",
        "body": ["이미지 전처리: 노이즈 제거 및 이진화", "문자 영역 검출: 텍스트 위치 파악", "문자 인식: 딥러닝 기반 분류"],
    },
    {
        "file": "sample_12.png",
        "text": "음성 인식 모델 발전",
        "subtitle": "HMM에서 Whisper까지",
        "body": ["HMM 기반: 통계적 음향 모델", "DNN-HMM: 딥러닝 결합 방식", "End-to-End: 입력에서 출력까지 직접 학습"],
    },
    {
        "file": "sample_13.png",
        "text": "기계 번역 방식 비교",
        "subtitle": "규칙 기반, 통계 기반, 신경망 기반",
        "body": ["규칙 기반: 언어 규칙 직접 작성", "통계 기반: 병렬 코퍼스 활용", "신경망 기반: 시퀀스-투-시퀀스 학습"],
    },
    {
        "file": "sample_14.png",
        "text": "WebSocket 실시간 통신",
        "subtitle": "서버-클라이언트 양방향 통신",
        "body": ["연결 유지: HTTP와 달리 지속 연결", "낮은 지연: 실시간 데이터 전송 적합", "이벤트 기반: 비동기 처리 지원"],
    },
    {
        "file": "sample_15.png",
        "text": "FastAPI 백엔드 구조",
        "subtitle": "비동기 API 서버 설계",
        "body": ["라우터: 엔드포인트 모듈화", "미들웨어: CORS 및 인증 처리", "WebSocket: 실시간 스트리밍 지원"],
    },
    {
        "file": "sample_16.png",
        "text": "BLEU 점수 해석",
        "subtitle": "기계 번역 품질 평가 기준",
        "body": ["0~10%: 거의 다름", "10~30%: 이해 가능한 수준", "30~40%: 좋은 번역", "40%+: 매우 우수"],
    },
    {
        "file": "sample_17.png",
        "text": "GPU 활용 딥러닝",
        "subtitle": "CUDA 기반 병렬 연산",
        "body": ["병렬 처리: 수천 개 코어 동시 연산", "메모리 관리: VRAM 효율적 사용", "혼합 정밀도: FP16으로 속도 향상"],
    },
    {
        "file": "sample_18.png",
        "text": "교육 플랫폼 요구사항",
        "subtitle": "실시간 강의 번역 시스템",
        "body": ["지연 시간 1초 이내 목표", "한국어 음성 인식 및 영어 번역", "슬라이드 텍스트 실시간 번역"],
    },
    {
        "file": "sample_19.png",
        "text": "시스템 성능 평가 결과",
        "subtitle": "ASR, MT, TTS, OCR 통합 지표",
        "body": ["ASR WER: 15% (기준 대비 개선)", "MT BLEU: 35% (양호한 번역 품질)", "TTS RTF: 0.3 (실시간 처리 가능)"],
    },
    {
        "file": "sample_20.png",
        "text": "향후 개발 계획",
        "subtitle": "기능 확장 및 성능 개선",
        "body": ["다국어 지원: 스페인어, 프랑스어 추가", "모바일 앱: Android/iOS 확장", "성능 최적화: 지연 시간 추가 단축"],
    },
    {
        "file": "sample_21.png",
        "text": "자기 지도 학습",
        "subtitle": "레이블 없이 표현 학습",
        "body": ["마스크 언어 모델: 빈칸 채우기로 학습", "대조 학습: 유사 샘플 가깝게 배치", "BERT: 양방향 인코더 표현 사전 훈련"],
    },
    {
        "file": "sample_22.png",
        "text": "확률적 경사 하강법",
        "subtitle": "SGD 변형 알고리즘",
        "body": ["미니배치: 일부 데이터로 기울기 추정", "모멘텀: 이전 기울기 방향 반영", "학습률 감소: 수렴 안정화"],
    },
    {
        "file": "sample_23.png",
        "text": "언어 모델 평가",
        "subtitle": "퍼플렉서티와 다운스트림 태스크",
        "body": ["퍼플렉서티: 낮을수록 좋은 언어 모델", "제로샷: 추가 학습 없이 태스크 수행", "퓨샷: 소수 예시만으로 적응"],
    },
    {
        "file": "sample_24.png",
        "text": "음성 합성 기술",
        "subtitle": "TTS 시스템 구조",
        "body": ["텍스트 분석: 발음 및 운율 예측", "음향 모델: 멜 스펙트로그램 생성", "보코더: 파형 신호 합성"],
    },
    {
        "file": "sample_25.png",
        "text": "이미지 세그멘테이션",
        "subtitle": "픽셀 단위 분류",
        "body": ["시맨틱: 클래스별 픽셀 분류", "인스턴스: 개별 객체 분리", "파노픽: 시맨틱 + 인스턴스 통합"],
    },
    {
        "file": "sample_26.png",
        "text": "분산 표현 학습",
        "subtitle": "Word2Vec과 GloVe",
        "body": ["CBOW: 주변 단어로 중심 단어 예측", "Skip-gram: 중심 단어로 주변 단어 예측", "GloVe: 전역 동시 출현 행렬 활용"],
    },
    {
        "file": "sample_27.png",
        "text": "모델 해석 기법",
        "subtitle": "블랙박스 모델 이해하기",
        "body": ["LIME: 국소적 선형 근사로 설명", "SHAP: 샤플리 값 기반 기여도 분석", "Grad-CAM: 시각화로 중요 영역 표시"],
    },
    {
        "file": "sample_28.png",
        "text": "연합 학습",
        "subtitle": "분산 환경에서의 프라이버시 보호",
        "body": ["로컬 학습: 각 기기에서 독립 훈련", "집계: 서버에서 가중치 평균화", "프라이버시: 원본 데이터 미전송"],
    },
    {
        "file": "sample_29.png",
        "text": "멀티모달 학습",
        "subtitle": "텍스트, 이미지, 음성 통합",
        "body": ["크로스 어텐션: 모달 간 정보 교환", "융합 방식: 초기/후기/중간 융합", "CLIP: 텍스트-이미지 공동 임베딩"],
    },
    {
        "file": "sample_30.png",
        "text": "추천 시스템",
        "subtitle": "협업 필터링과 콘텐츠 기반",
        "body": ["협업 필터링: 유사 사용자 패턴 활용", "콘텐츠 기반: 아이템 특성 분석", "하이브리드: 두 방식 결합"],
    },
    {
        "file": "sample_31.png",
        "text": "시계열 예측",
        "subtitle": "LSTM과 Temporal Fusion Transformer",
        "body": ["LSTM: 장기 의존성 학습", "GRU: 경량화된 게이트 구조", "TFT: 어텐션 기반 다변량 예측"],
    },
    {
        "file": "sample_32.png",
        "text": "이상 탐지",
        "subtitle": "비정상 패턴 감지",
        "body": ["통계적 방법: Z-score, IQR 기반", "오토인코더: 재구성 오차 활용", "아이솔레이션 포레스트: 고립도 측정"],
    },
    {
        "file": "sample_33.png",
        "text": "그래프 신경망",
        "subtitle": "관계 데이터 학습",
        "body": ["노드 분류: 개별 노드 레이블 예측", "링크 예측: 엣지 존재 여부 예측", "그래프 분류: 전체 그래프 특성 분류"],
    },
    {
        "file": "sample_34.png",
        "text": "ONNX 모델 배포",
        "subtitle": "플랫폼 독립적 추론",
        "body": ["변환: PyTorch/TF 모델을 ONNX로", "최적화: 불필요 연산 제거", "런타임: CPU/GPU 모두 지원"],
    },
    {
        "file": "sample_35.png",
        "text": "데이터 파이프라인",
        "subtitle": "수집부터 서빙까지",
        "body": ["수집: 크롤링 및 API 연동", "전처리: 정제 및 변환", "서빙: 실시간 피처 제공"],
    },
    {
        "file": "sample_36.png",
        "text": "능동 학습",
        "subtitle": "효율적인 레이블링 전략",
        "body": ["불확실성 샘플링: 모델이 불확실한 샘플 선택", "다양성 샘플링: 다양한 샘플 커버", "배치 모드: 여러 샘플 동시 선택"],
    },
    {
        "file": "sample_37.png",
        "text": "도메인 적응",
        "subtitle": "소스-타겟 도메인 간 전이",
        "body": ["파인튜닝: 타겟 도메인 소량 데이터 활용", "도메인 적대 훈련: 도메인 불변 표현 학습", "데이터 증강: 타겟 분포 모사"],
    },
    {
        "file": "sample_38.png",
        "text": "신경망 아키텍처 탐색",
        "subtitle": "AutoML과 NAS",
        "body": ["탐색 공간: 레이어 수, 채널 수 등", "탐색 전략: 강화학습, 진화 알고리즘", "성능 추정: 조기 중단으로 효율화"],
    },
    {
        "file": "sample_39.png",
        "text": "스트리밍 처리 아키텍처",
        "subtitle": "실시간 데이터 처리",
        "body": ["버퍼링: 청크 단위 오디오 수집", "파이프라인: ASR-MT-TTS 순차 처리", "지연 최적화: 각 단계 병렬화"],
    },
    {
        "file": "sample_40.png",
        "text": "Electron 데스크톱 앱",
        "subtitle": "웹 기술 기반 크로스 플랫폼",
        "body": ["화면 공유: desktopCapturer API", "WebRTC: 실시간 스트리밍", "IPC: 메인-렌더러 프로세스 통신"],
    },
    {
        "file": "sample_41.png",
        "text": "React 컴포넌트 설계",
        "subtitle": "프론트엔드 아키텍처",
        "body": ["상태 관리: Zustand 전역 상태", "WebSocket 훅: 실시간 데이터 수신", "자막 오버레이: Canvas 기반 렌더링"],
    },
    {
        "file": "sample_42.png",
        "text": "CI/CD 파이프라인",
        "subtitle": "GitLab 기반 자동화",
        "body": ["빌드: Docker 이미지 자동 생성", "테스트: 유닛 및 통합 테스트", "배포: 스테이징 및 프로덕션 자동 배포"],
    },
    {
        "file": "sample_43.png",
        "text": "보안 고려사항",
        "subtitle": "AI 시스템 보안",
        "body": ["입력 검증: 악의적 입력 필터링", "모델 보안: 적대적 공격 방어", "데이터 암호화: 전송 및 저장 보호"],
    },
    {
        "file": "sample_44.png",
        "text": "성능 모니터링",
        "subtitle": "운영 중 모델 품질 관리",
        "body": ["드리프트 감지: 입력 분포 변화 모니터링", "지표 추적: WER, BLEU 실시간 집계", "알람: 성능 저하 시 자동 알림"],
    },
    {
        "file": "sample_45.png",
        "text": "A/B 테스트",
        "subtitle": "모델 비교 실험 설계",
        "body": ["트래픽 분할: 사용자 무작위 배정", "지표 비교: 통계적 유의성 검정", "롤백: 성능 저하 시 이전 모델 복구"],
    },
    {
        "file": "sample_46.png",
        "text": "엣지 컴퓨팅",
        "subtitle": "온디바이스 AI 추론",
        "body": ["모델 경량화: 양자화 및 가지치기", "지연 감소: 클라우드 의존 최소화", "프라이버시: 데이터 로컬 처리"],
    },
    {
        "file": "sample_47.png",
        "text": "다국어 번역 모델",
        "subtitle": "NLLB와 OPUS-MT 비교",
        "body": ["OPUS-MT: 언어 쌍별 특화 모델", "NLLB-200: 200개 언어 단일 모델", "성능 비교: 도메인별 BLEU 차이"],
    },
    {
        "file": "sample_48.png",
        "text": "음성 인식 오류 분석",
        "subtitle": "WER 개선 전략",
        "body": ["삽입 오류: 없는 단어가 추가됨", "삭제 오류: 있는 단어가 빠짐", "대체 오류: 다른 단어로 인식됨"],
    },
    {
        "file": "sample_49.png",
        "text": "실험 결과 요약",
        "subtitle": "베이스라인 대비 성능 개선",
        "body": ["ASR WER: 23% → 15% (개선)", "MT BLEU: 28% → 35% (개선)", "TTS RTF: 0.8 → 0.3 (개선)"],
    },
    {
        "file": "sample_50.png",
        "text": "결론 및 향후 연구",
        "subtitle": "프로젝트 성과와 과제",
        "body": ["목표 달성: 실시간 강의 번역 구현", "한계점: 전문 용어 번역 정확도 개선 필요", "향후 계획: 다국어 지원 및 모바일 확장"],
    },
]


# ──────────────────────────────────────────────
# OCR PNG 생성
# ──────────────────────────────────────────────
def generate_ocr_samples():
    print("\n[OCR] 슬라이드 이미지 생성 중...")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[OCR] Pillow 미설치: pip install Pillow")
        return

    OCR_DIR.mkdir(parents=True, exist_ok=True)

    font_candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        "C:/Windows/Fonts/batang.ttc",
    ]
    font_path = next((p for p in font_candidates if Path(p).exists()), None)

    generated = []

    for sample in OCR_SAMPLES:
        output_path = OCR_DIR / sample["file"]

        try:
            img = Image.new("RGB", (1280, 720), color=(255, 255, 255))
            draw = ImageDraw.Draw(img)

            draw.rectangle([0, 0, 1280, 100], fill=(30, 80, 160))

            if font_path:
                font_title    = ImageFont.truetype(font_path, 42)
                font_subtitle = ImageFont.truetype(font_path, 28)
                font_body     = ImageFont.truetype(font_path, 24)
            else:
                font_title = font_subtitle = font_body = ImageFont.load_default()

            draw.text((40, 25), sample["text"], font=font_title, fill=(255, 255, 255))
            draw.rectangle([40, 120, 1240, 123], fill=(30, 80, 160))
            draw.text((40, 140), sample["subtitle"], font=font_subtitle, fill=(50, 50, 50))

            y = 210
            for line in sample["body"]:
                draw.text((60, y), line, font=font_body, fill=(30, 30, 30))
                y += 60

            draw.text((1200, 690), sample["file"].replace(".png", ""), font=font_body, fill=(150, 150, 150))

            img.save(str(output_path), "PNG")

            full_text = " ".join([sample["text"], sample["subtitle"]] + sample["body"])
            generated.append({"file": sample["file"], "text": full_text})

            print(f"  ✅ {sample['file']}")

        except Exception as e:
            print(f"  ❌ {sample['file']} 생성 실패: {e}")

    gt_path = OCR_DIR / "ground_truth.json"
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(generated, f, ensure_ascii=False, indent=2)

    print(f"\n[OCR] {len(generated)}개 생성 완료 → {OCR_DIR}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="평가용 OCR 샘플 데이터 생성")
    parser.parse_args()

    print("=" * 50)
    print("평가용 OCR 샘플 데이터 생성")
    print("=" * 50)

    generate_ocr_samples()

    print("\n완료.")


if __name__ == "__main__":
    main()
