"""
자막(transcript) 라우터
강의 중 ASR/NMT 결과를 JSONL로 실시간 append,
강의 종료 시 최종 JSON으로 병합. JSON/SRT/TXT 다운로드 지원.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.config import DATA_ROOT

router = APIRouter(prefix="/transcripts", tags=["Transcripts"])

# 자막 저장 경로 — DATA_ROOT 기준 (frozen: %LOCALAPPDATA%\Aunion AI\, dev: <repo>/).
# install dir 재설치로 덮어써져도 자막 보존.
TRANSCRIPTS_DIR = DATA_ROOT / "uploads" / "transcripts"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# 활성 세션 상태 (메모리)
# key: session_id
# value: {slide_id, started_at, started_at_monotonic, next_seq}
active_sessions: dict[str, dict] = {}


# ── Pydantic 모델 ────────────────────────────────────────────────
class TranscriptSegment(BaseModel):
    seq: int
    t_offset: float      # 강의 시작 기준 초
    ts_utc: str          # ISO8601 절대 시간
    original: str
    translated: str
    slide_id: Optional[str] = None
    page: Optional[int] = None


class TranscriptMeta(BaseModel):
    session_id: str
    slide_id: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    total_segments: int


class TranscriptFull(BaseModel):
    meta: TranscriptMeta
    segments: list[TranscriptSegment]


# ── 파일 경로 헬퍼 ──────────────────────────────────────────────
def _meta_path(session_id: str) -> Path:
    return TRANSCRIPTS_DIR / f"{session_id}.meta.json"


def _jsonl_path(session_id: str) -> Path:
    return TRANSCRIPTS_DIR / f"{session_id}.jsonl"


def _final_path(session_id: str) -> Path:
    return TRANSCRIPTS_DIR / f"{session_id}.json"


# ── 세션 라이프사이클 (ws.py에서 호출) ──────────────────────────
def start_session(slide_id: Optional[str]) -> str:
    """새 강의 세션 시작. session_id 발급 + meta 파일 기록."""
    session_id = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc).isoformat()

    meta = {
        "session_id": session_id,
        "slide_id": slide_id,
        "started_at": started_at,
        "ended_at": None,
        "total_segments": 0,
    }

    with open(_meta_path(session_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    active_sessions[session_id] = {
        "slide_id": slide_id,
        "started_at": started_at,
        "started_at_monotonic": time.monotonic(),
        "next_seq": 0,
    }

    print(f"[Transcripts] 세션 시작: {session_id} (slide={slide_id})")
    return session_id


def append_segment(
    session_id: str,
    original: str,
    translated: str,
    slide_id: Optional[str] = None,
    page: Optional[int] = None,
) -> None:
    """번역 결과를 JSONL 한 줄로 append. 세션 비활성이면 무시.
    slide_id / page: 발화 시작 시점의 페이지. 다운로드 자막에 메타로 표시.
    """
    session = active_sessions.get(session_id)
    if session is None:
        return

    seq = session["next_seq"]
    t_offset = round(time.monotonic() - session["started_at_monotonic"], 3)
    ts_utc = datetime.now(timezone.utc).isoformat()

    segment = {
        "seq": seq,
        "t_offset": t_offset,
        "ts_utc": ts_utc,
        "original": original,
        "translated": translated,
        "slide_id": slide_id,
        "page": page,
    }

    with open(_jsonl_path(session_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(segment, ensure_ascii=False) + "\n")

    session["next_seq"] = seq + 1


def end_session(session_id: Optional[str]) -> Optional[str]:
    """
    세션 종료: jsonl + meta 병합 → 최종 {session_id}.json 생성.
    None 전달 또는 비활성 세션이면 no-op.
    """
    if not session_id or session_id not in active_sessions:
        return None

    session = active_sessions.pop(session_id)
    ended_at = datetime.now(timezone.utc).isoformat()

    # jsonl 읽어서 세그먼트 복원
    segments: list[dict] = []
    jsonl = _jsonl_path(session_id)
    if jsonl.exists():
        with open(jsonl, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    segments.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 손상된 줄 스킵

    meta = {
        "session_id": session_id,
        "slide_id": session["slide_id"],
        "started_at": session["started_at"],
        "ended_at": ended_at,
        "total_segments": len(segments),
    }

    # meta 갱신 + 병합본 생성
    with open(_meta_path(session_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    with open(_final_path(session_id), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "segments": segments}, f, ensure_ascii=False, indent=2)

    print(f"[Transcripts] 세션 종료: {session_id} ({len(segments)}개 세그먼트)")
    return session_id


# ── 포맷 변환 ───────────────────────────────────────────────────
def _fmt_srt_time(seconds: float) -> str:
    """SRT 타임코드: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def _to_srt(segments: list[dict], default_duration: float = 4.0) -> str:
    """세그먼트 → SRT. 종료시간은 다음 세그먼트 시작, 마지막은 +default_duration."""
    lines: list[str] = []
    for i, seg in enumerate(segments):
        start = float(seg["t_offset"])
        if i + 1 < len(segments):
            end = float(segments[i + 1]["t_offset"])
            if end - start > 10:  # 공백이 너무 긴 경우 방지
                end = start + default_duration
        else:
            end = start + default_duration

        lines.append(str(i + 1))
        lines.append(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}")
        lines.append(seg.get("original", ""))
        lines.append(seg.get("translated", ""))
        lines.append("")
    return "\n".join(lines)


def _to_txt(segments: list[dict]) -> str:
    """세그먼트 → 평문. 페이지 정보가 있으면 시간 옆에 (page N) 으로 표시."""
    lines: list[str] = []
    for seg in segments:
        t = int(float(seg["t_offset"]))
        mins, secs = divmod(t, 60)
        page = seg.get("page")
        page_tag = f" (page {page})" if isinstance(page, int) else ""
        lines.append(f"[{mins:02d}:{secs:02d}]{page_tag} {seg.get('original', '')}")
        lines.append(f"          → {seg.get('translated', '')}")
    return "\n".join(lines)


# ── HTTP 엔드포인트 ─────────────────────────────────────────────
@router.get("")
async def list_transcripts():
    """저장된 세션 목록 (started_at 내림차순)"""
    sessions: list[dict] = []
    for meta_file in TRANSCRIPTS_DIR.glob("*.meta.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                sessions.append(json.load(f))
        except Exception:
            continue
    sessions.sort(key=lambda m: m.get("started_at", ""), reverse=True)
    return {"sessions": sessions}


@router.get("/{session_id}")
async def get_transcript(session_id: str):
    """최종 JSON 조회 (종료된 세션만)"""
    path = _final_path(session_id)
    if not path.exists():
        raise HTTPException(404, "자막을 찾을 수 없습니다")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/{session_id}/download")
async def download_transcript(
    session_id: str,
    format: Literal["json", "srt", "txt"] = "json",
):
    """자막 다운로드 (json/srt/txt)"""
    final = _final_path(session_id)
    if not final.exists():
        raise HTTPException(404, "자막을 찾을 수 없습니다")

    if format == "json":
        return FileResponse(
            final,
            media_type="application/json",
            filename=f"transcript_{session_id}.json",
        )

    with open(final, "r", encoding="utf-8") as f:
        data = json.load(f)
    segments = data.get("segments", [])

    if format == "srt":
        body = _to_srt(segments)
        return Response(
            content=body,
            media_type="application/x-subrip",
            headers={
                "Content-Disposition": f'attachment; filename="transcript_{session_id}.srt"'
            },
        )

    # format == "txt"
    body = _to_txt(segments)
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="transcript_{session_id}.txt"'
        },
    )


@router.delete("/{session_id}")
async def delete_transcript(session_id: str):
    """자막 삭제 (meta/jsonl/final 모두)"""
    deleted: list[str] = []
    for p in (_meta_path(session_id), _jsonl_path(session_id), _final_path(session_id)):
        if p.exists():
            p.unlink()
            deleted.append(p.name)
    if not deleted:
        raise HTTPException(404, "자막을 찾을 수 없습니다")
    active_sessions.pop(session_id, None)
    return {"deleted": deleted}
