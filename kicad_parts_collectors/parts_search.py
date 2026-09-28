from __future__ import annotations

import json
import urllib.request

from easyeda2kicad.easyeda.easyeda_api import EasyedaApi, JLCPCB_SEARCH_API


PAGE_SIZE = 20


def library_specs(entry) -> list[tuple[str, str]]:
    specs = [("심볼", entry.symbol), ("부품명", entry.value),
             ("풋프린트", entry.footprint), ("3D 모델", entry.model),
             ("데이터시트", entry.datasheet), ("설명", entry.description)]
    return [(name, value) for name, value in specs if value] + [
        (name, value) for name, value in entry.properties.items() if value]


def part_specs(part: dict) -> list[tuple[str, str]]:
    fields = (("LCSC", "componentCode"), ("부품명", "componentModelEn"),
              ("제조사", "componentBrandEn"), ("패키지", "componentSpecificationEn"),
              ("카테고리", "componentTypeEn"), ("재고", "stockCount"),
              ("설명", "describe"), ("데이터시트", "dataManualUrl"))
    specs = [(label, str(part[key])) for label, key in fields
             if part.get(key) not in (None, "")]
    attributes = [(str(item.get("attribute_name_en") or "사양"), str(item["attribute_value_name"]))
                  for item in (part.get("attributes") or [])
                  if item.get("attribute_value_name") not in (None, "", "-")]
    return specs + (attributes or [("상세 사양", "제공된 상세 사양 없음")])


def search_parts(keyword: str, page: int = 1) -> dict:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("검색어를 입력하세요.")
    api = EasyedaApi(use_cache=False)
    request = urllib.request.Request(
        JLCPCB_SEARCH_API,
        data=json.dumps({"keyword": keyword, "currentPage": page, "pageSize": PAGE_SIZE}).encode("utf-8"),
        headers={**api.headers, "Content-Type": "application/json",
                 "Origin": "https://jlcpcb.com", "Referer": "https://jlcpcb.com/parts"},
    )
    # 기존 모듈은 통신 오류를 빈 결과로 반환하므로, 여기서는 오류와 검색 결과 없음을 구분한다.
    with urllib.request.urlopen(request, timeout=15, context=api.ssl_context) as response:
        payload = json.loads(api._decode_response(response.read()))
    info = (payload.get("data") or {}).get("componentPageInfo")
    if payload.get("code") != 200 or not isinstance(info, dict):
        raise ValueError("JLCPCB 검색 응답을 확인할 수 없습니다. 잠시 후 다시 시도하세요.")
    rows = info.get("list")
    if rows is None and info.get("total") == 0:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("JLCPCB 검색 목록 형식이 올바르지 않습니다.")
    return {"results": rows, "total": int(info.get("total") or 0)}
