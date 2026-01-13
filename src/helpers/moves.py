from bs4 import BeautifulSoup
import json
import re
from pathlib import Path

def clean_text(s: str) -> str:
    # Normalize whitespace/newlines into single spaces
    return re.sub(r"\s+", " ", s).strip()

def parse_int_maybe(s: str):
    s = clean_text(s)
    # Bulbapedia sometimes uses "—" for power/acc/etc.
    if s in {"—", "-", ""}:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def parse_moves_html(html: str):
    soup = BeautifulSoup(html, "html.parser")

    # Prefer the moves table by class if present; fallback to first table
    table = soup.select_one("table.jquery-tablesorter") or soup.find("table")
    if not table:
        raise RuntimeError("No <table> found in HTML.")

    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr")

    moves = []
    for row in rows:
        # Only direct cell children (avoids grabbing nested tds if any)
        cols = row.find_all("td", recursive=False)
        if len(cols) < 8:
            continue

        move_id = parse_int_maybe(cols[0].get_text(" ", strip=True))
        if move_id is None:
            continue

        name = clean_text(cols[1].get_text(" ", strip=True))
        type_ = clean_text(cols[2].get_text(" ", strip=True))
        category = clean_text(cols[3].get_text(" ", strip=True))

        pp = parse_int_maybe(cols[4].get_text(" ", strip=True))

        # Power can be "—" for status moves
        power = parse_int_maybe(cols[5].get_text(" ", strip=True))

        # Accuracy can be "—" for always-hits moves; keep as string or None
        acc_raw = clean_text(cols[6].get_text(" ", strip=True))
        accuracy = None if acc_raw in {"—", "-", ""} else acc_raw

        gen = clean_text(cols[7].get_text(" ", strip=True))

        moves.append({
            "id": move_id,
            "name": name,
            "type": type_,
            "category": category,
            "pp": pp,
            "power": power,
            "accuracy": accuracy,
            "generation": gen,
        })

    return moves

def main():
    in_path = Path("test.html")   # <-- put your downloaded/copied html here
    out_path = Path("moves.json")

    html = in_path.read_text(encoding="utf-8", errors="replace")
    moves = parse_moves_html(html)

    out_path.write_text(json.dumps(moves, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Parsed {len(moves)} moves -> {out_path.resolve()}")

    # sanity check: print first 3
    print(json.dumps(moves[:3], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
