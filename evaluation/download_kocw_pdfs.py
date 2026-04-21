"""
KOCW 한국어 강의 PDF 자동 다운로더

kocw.net 공개 API를 이용해 분야별 강의 PDF를 자동 다운로드합니다.
다운로드된 PDF는 evaluation/datasets/ocr_samples/ 에 저장됩니다.
이후 rebuild_ocr_dataset.py 를 실행하면 OCR 평가 데이터셋이 생성됩니다.

흐름:
  1. POST /home/search/search.do  → 강의 cid 목록
  2. GET  /home/cview.do?cid=XXX  → kemId 추출
  3. POST /home/special/lectures.do (kemId=XXX) → 차시별 파일 JSON
  4. mimeType="text/pdf" 인 항목만 CDN URL에서 다운로드

사용법:
    pip install requests
    python evaluation/download_kocw_pdfs.py
"""

import sys
import json
import time
import random
import re
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDF_DIR  = Path(__file__).parent / "datasets" / "ocr_samples"
BASE_URL = "https://www.kocw.net"
CDN_URL  = "http://kocw-n.xcache.kinxcdn.com"  # PDF CDN
TARGET_PDF_PER_KEYWORD = 8   # 키워드당 강의 수 (더 많이 시도)
MAX_PDF_PER_COURSE     = 5   # 강의당 최대 PDF 차시
TARGET_TOTAL           = 100  # 전체 목표 PDF 개수

# 역사/심리/사회과학 보충 전용
SEARCH_KEYWORDS = [
    # 역사 (현재 35개 → 대폭 보충)
    "세계사",
    "동양사",
    "서양사",
    "한국근현대사",
    "고대사",
    "중세사",
    "한국문화사",
    "역사입문",
    "동아시아역사",
    "문명사",
    # 교육/심리 (현재 0개 → 최우선)
    "심리학개론",
    "인지심리학",
    "사회심리학",
    "교육심리학",
    "상담이론",
    "발달심리학",
    "이상심리학",
    "성격심리학",
    "학습심리학",
    "교육학개론",
    # 사회과학 보충 (정치학개론 41, 사회학개론 16 → 보충)
    "사회복지론",
    "정치사상",
    "비교정치",
    "행정학",
    "공공정책",
    "사회조사방법론",
    # 자연과학 보충 (물리87, 미적분2 → 보충)
    "대학물리학",
    "물리화학",
    "일반생물학",
    "미분방정식",
    "확률론",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def get_session():
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        s = requests.Session()
        s.headers.update(HEADERS)
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://",  HTTPAdapter(max_retries=retry))
        return s
    except ImportError:
        print("[ERROR] requests 미설치: pip install requests")
        sys.exit(1)


def search_cids(session, keyword: str) -> list[str]:
    """키워드로 KOCW 검색 → cid 목록 반환"""
    url = f"{BASE_URL}/home/search/search.do"
    data = {
        "query": keyword,
        "callStatus": "", "open_top_select": "znAll", "oldQuery": "",
        "iStartCount": "0", "iGroupView": "5", "colName": "all",
        "exQuery": "", "strQuery": "", "onHanja": "false", "s_contentFileType": "",
    }
    headers = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    try:
        resp = session.post(url, data=data, headers=headers, timeout=15)
        text = resp.content.decode("euc-kr", errors="replace")
        cids = list(dict.fromkeys(re.findall(r"/home/cview\.do\?cid=([a-f0-9]+)", text)))
        return cids[:TARGET_PDF_PER_KEYWORD]
    except Exception as e:
        print(f"    [검색 실패] {e}")
        return []


def get_kem_id(session, cid: str) -> str | None:
    """강의 페이지에서 kemId 추출"""
    url = f"{BASE_URL}/home/cview.do?cid={cid}"
    try:
        resp = session.get(url, timeout=15)
        text = resp.content.decode("euc-kr", errors="replace")
        # kemId는 숫자형 ID (보통 7자리)
        match = re.search(r"kemId\s*[=,]\s*['\"]?(\d{5,8})['\"]?", text)
        if match:
            return match.group(1)
        # 대안: getLectures(obj, 'XXXXXXX', ...) 패턴
        match2 = re.search(r"getLectures\s*\([^,]+,\s*['\"](\d+)['\"]", text)
        if match2:
            return match2.group(1)
        # thumbnail URL에서 추출 (thumbnail/07/t1442546.jpg → 1442546)
        match3 = re.search(r"thumbnail/\d+/t(\d+)\.", text)
        if match3:
            return match3.group(1)
    except Exception as e:
        print(f"      [kemId 추출 실패] {e}")
    return None


def get_pdf_urls(session, kem_id: str) -> list[dict]:
    """lectures.do API → PDF 차시 URL 목록"""
    url = f"{BASE_URL}/home/special/lectures.do"
    headers = {
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/home/cview.do",
    }
    try:
        resp = session.post(url, data=f"kemId={kem_id}", headers=headers, timeout=15)
        data = json.loads(resp.text)
        results = []
        for group in data:
            for lecture in group.get("lectures", []):
                mime = lecture.get("mimeType", "")
                loc  = lecture.get("location", "")
                if "pdf" in mime.lower() and loc.startswith("http"):
                    results.append({
                        "url":   loc,
                        "title": lecture.get("title", "unknown"),
                        "id":    lecture.get("id", ""),
                    })
        return results[:MAX_PDF_PER_COURSE]
    except Exception as e:
        print(f"      [API 실패] {e}")
        return []


def download_pdf(session, pdf_info: dict, save_path: Path) -> bool:
    """PDF CDN에서 다운로드 후 저장"""
    if save_path.exists():
        return False
    try:
        resp = session.get(pdf_info["url"], timeout=30, stream=True)
        if resp.status_code != 200:
            return False

        ct = resp.headers.get("Content-Type", "")
        if "html" in ct:
            return False

        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # PDF 매직 바이트 검증
        with open(save_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            save_path.unlink()
            return False

        return True
    except Exception as e:
        if save_path.exists():
            save_path.unlink()
        print(f"      [다운로드 오류] {e}")
        return False


def main():
    print("=" * 60)
    print("KOCW 한국어 강의 PDF 자동 다운로더")
    print("=" * 60)

    try:
        import requests  # noqa: F401
    except ImportError:
        print("\n[ERROR] requests 미설치: pip install requests")
        sys.exit(1)

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()

    total_downloaded = 0
    visited_cids: set[str] = set()

    for keyword in SEARCH_KEYWORDS:
        if total_downloaded >= TARGET_TOTAL:
            break

        print(f"\n[검색] '{keyword}'")
        cids = search_cids(session, keyword)

        if not cids:
            print("  검색 결과 없음")
            time.sleep(1)
            continue

        print(f"  강의 {len(cids)}개 발견: {cids}")

        for cid in cids:
            if total_downloaded >= TARGET_TOTAL:
                break
            if cid in visited_cids:
                continue
            visited_cids.add(cid)

            kem_id = get_kem_id(session, cid)
            if not kem_id:
                print(f"  [{cid}] kemId 없음 → 건너뜀")
                continue

            print(f"  [{cid}] kemId={kem_id}")
            pdf_list = get_pdf_urls(session, kem_id)

            if not pdf_list:
                print(f"    PDF 없음")
                continue

            print(f"    PDF {len(pdf_list)}개 발견")
            downloaded_this = 0

            for pdf in pdf_list:
                safe_title = re.sub(r'[^\w가-힣]', '_', pdf['title'])[:30]
                filename   = f"{keyword}_{kem_id}_{pdf['id']}_{safe_title}.pdf"
                save_path  = PDF_DIR / filename

                ok = download_pdf(session, pdf, save_path)
                if ok:
                    size_kb = save_path.stat().st_size // 1024
                    print(f"    [완료] {filename} ({size_kb} KB)")
                    total_downloaded += 1
                    downloaded_this  += 1
                    time.sleep(random.uniform(0.3, 0.8))
                else:
                    print(f"    [실패] {pdf['title']}")

            if downloaded_this > 0:
                time.sleep(random.uniform(0.5, 1.5))

        time.sleep(random.uniform(1, 2))

    print("\n" + "=" * 60)
    if total_downloaded == 0:
        print("다운로드된 PDF가 없습니다.")
        print("네트워크 연결 또는 KOCW 사이트 상태를 확인해주세요.")
    else:
        print(f"완료: PDF {total_downloaded}개 다운로드")
        print(f"저장 위치: {PDF_DIR}")
        print()
        print("다음 단계:")
        print("  python evaluation/rebuild_ocr_dataset.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
