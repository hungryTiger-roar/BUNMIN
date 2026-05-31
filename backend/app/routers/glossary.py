"""
용어집(glossary) 관리 API

사용자가 번역 용어집을 동적으로 추가/수정/삭제할 수 있도록 지원.
과목(카테고리)별로 용어를 그룹화하여 관리.
"""
import csv
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/glossary", tags=["glossary"])

# glossary.csv 경로
CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"
GLOSSARY_PATH = CONFIG_DIR / "glossary.csv"


class GlossaryEntry(BaseModel):
    korean: str
    english: str
    category: Optional[str] = "일반"


class GlossaryUpdateRequest(BaseModel):
    korean: str
    english: str
    category: Optional[str] = None


def _parse_glossary() -> tuple[list[dict], dict[str, list[dict]]]:
    """glossary.csv 파싱하여 엔트리 목록과 카테고리별 그룹 반환"""
    entries = []
    by_category = {}
    current_category = "일반"

    if not GLOSSARY_PATH.exists():
        return entries, by_category

    with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and row and row[0].lower() == "korean":
                continue  # 헤더 스킵

            if not row or not row[0].strip():
                continue

            line = row[0].strip()

            # 주석으로 카테고리 감지: # ===== 카테고리명 =====
            if line.startswith("#"):
                match = re.search(r"=+\s*(.+?)\s*=+", line)
                if match:
                    current_category = match.group(1).strip()
                continue

            if len(row) >= 2:
                korean = row[0].strip()
                english = row[1].strip()
                entry = {
                    "id": i,
                    "korean": korean,
                    "english": english,
                    "category": current_category
                }
                entries.append(entry)

                if current_category not in by_category:
                    by_category[current_category] = []
                by_category[current_category].append(entry)

    return entries, by_category


def _save_glossary(entries: list[dict], categories_order: list[str] = None):
    """용어집을 CSV 파일로 저장 (카테고리별 그룹화)"""
    # 카테고리별로 그룹화
    by_category = {}
    for entry in entries:
        cat = entry.get("category", "일반")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(entry)

    # 카테고리 순서 결정 (일반 먼저, 나머지는 알파벳)
    if categories_order:
        ordered_cats = categories_order
    else:
        ordered_cats = ["일반"] + sorted([c for c in by_category.keys() if c != "일반"])

    with open(GLOSSARY_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["korean", "english"])

        for cat in ordered_cats:
            if cat not in by_category:
                continue

            # 카테고리 주석 추가
            if cat != "일반" or len(by_category) > 1:
                writer.writerow([f"# ===== {cat} =====", ""])

            for entry in by_category[cat]:
                writer.writerow([entry["korean"], entry["english"]])


@router.get("")
async def get_glossary():
    """전체 용어집 조회"""
    entries, by_category = _parse_glossary()
    categories = list(by_category.keys())
    return {
        "entries": entries,
        "categories": categories,
        "total": len(entries)
    }


@router.get("/categories")
async def get_categories():
    """카테고리 목록 조회"""
    _, by_category = _parse_glossary()
    return {
        "categories": [
            {"name": cat, "count": len(items)}
            for cat, items in by_category.items()
        ]
    }


@router.post("")
async def add_entry(entry: GlossaryEntry):
    """새 용어 추가"""
    entries, _ = _parse_glossary()

    # 중복 체크
    for e in entries:
        if e["korean"] == entry.korean:
            raise HTTPException(status_code=400, detail=f"'{entry.korean}' 용어가 이미 존재합니다")

    new_entry = {
        "id": max([e["id"] for e in entries], default=0) + 1,
        "korean": entry.korean,
        "english": entry.english,
        "category": entry.category or "일반"
    }
    entries.append(new_entry)
    _save_glossary(entries)

    return {"success": True, "entry": new_entry}


@router.put("/{korean}")
async def update_entry(korean: str, update: GlossaryUpdateRequest):
    """용어 수정 (korean을 키로 사용)"""
    entries, _ = _parse_glossary()

    found = False
    for entry in entries:
        if entry["korean"] == korean:
            entry["korean"] = update.korean
            entry["english"] = update.english
            if update.category:
                entry["category"] = update.category
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"'{korean}' 용어를 찾을 수 없습니다")

    _save_glossary(entries)
    return {"success": True}


@router.delete("/{korean}")
async def delete_entry(korean: str):
    """용어 삭제"""
    entries, _ = _parse_glossary()

    original_len = len(entries)
    entries = [e for e in entries if e["korean"] != korean]

    if len(entries) == original_len:
        raise HTTPException(status_code=404, detail=f"'{korean}' 용어를 찾을 수 없습니다")

    _save_glossary(entries)
    return {"success": True}


@router.post("/category")
async def add_category(name: str):
    """새 카테고리 추가 (빈 카테고리)"""
    # 카테고리는 용어 추가 시 자동 생성되므로 별도 처리 불필요
    return {"success": True, "category": name}


@router.delete("/category/{name}")
async def delete_category(name: str):
    """카테고리 삭제 (해당 카테고리의 용어들은 '일반'으로 이동)"""
    entries, _ = _parse_glossary()

    for entry in entries:
        if entry.get("category") == name:
            entry["category"] = "일반"

    _save_glossary(entries)
    return {"success": True}
