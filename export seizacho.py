#!/usr/bin/env python3
"""
export_seizacho.py — 星座帳 公開エクスポート
SQLite の承認済み星座だけを entries.json に書き出し、確認の上で push する。

原則(§4.5):
  - 公開層フィールドのみ書き出す(ホワイトリスト方式。それ以外は物理的に通らない)
  - status='approved' 以外は絶対に出さない
  - 一方通行: このスクリプトは SQLite を読むだけで、書き込まない

使い方:
  python3 export_seizacho.py           # diff確認 → y/n → commit & push
  python3 export_seizacho.py --dry-run # 書き出し内容の確認のみ(git操作なし)
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# ══════════ 設定(環境に合わせてここだけ直す) ══════════

DB_PATH   = Path.home() / "koyomi" / "koyomi.db"          # 星座帳のSQLite
SITE_REPO = Path.home() / "seizacho-site"                  # サイトのgitリポジトリ
JSON_NAME = "entries.json"

# 星IDを不透明トークンに変換するためのソルト。
# 一度公開を始めたら変更しないこと(全ての点の座標が変わってしまう)。
# 初回に適当な長いランダム文字列に差し替える。
HOSHI_SALT = "kokode-kaeru-himitsu-no-shio"

# 承認済み星座を公開層スキーマで返すクエリ。
# ここが唯一のDB接点。テーブル/カラム名は実スキーマに合わせて調整する。
# hoshi_ids は紐づく星(内部レコード)のIDのみ。中身のカラムは一切選択しない。
QUERY = """
SELECT
  c.date          AS date,
  c.name          AS name,
  c.diary         AS diary,
  (SELECT GROUP_CONCAT(h.id) FROM hoshi h
    WHERE h.constellation_id = c.id)     AS hoshi_ids,
  c.vod_url       AS url
FROM constellations c
WHERE c.status = 'approved'
ORDER BY c.date ASC
"""

# ══════════ 検証(公開前の最後の砦) ══════════

PUBLIC_FIELDS = ("date", "name", "diary", "hoshi", "url")  # これ以外は捨てる
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE  = re.compile(r"^https://(www\.)?(youtube\.com|youtu\.be)/")

def hoshi_token(star_id):
    """内部IDをソルト付きハッシュで不透明トークン化(公開側からIDは復元不能)"""
    import hashlib
    return hashlib.sha256(f"{HOSHI_SALT}:{star_id}".encode()).hexdigest()[:12]

def validate(rows):
    errors = []
    seen = set()
    out = []
    for i, r in enumerate(rows):
        ids = [s for s in (r.get("hoshi_ids") or "").split(",") if s]
        r = dict(r)
        r["hoshi"] = [hoshi_token(s) for s in ids]
        e = {k: r[k] for k in PUBLIC_FIELDS if r.get(k) not in (None, "", [])}
        tag = f"[{i}] {r.get('date','?')} {r.get('name','?')}"
        if not DATE_RE.match(e.get("date", "")):
            errors.append(f"{tag}: date が YYYY-MM-DD でない")
        if not e.get("name"):
            errors.append(f"{tag}: name が空")
        if not e.get("diary"):
            errors.append(f"{tag}: diary が空")
        if not e.get("hoshi"):
            errors.append(f"{tag}: 紐づく星が0件(星のない星座は公開できない)")
        if "url" in e and not URL_RE.match(e["url"]):
            errors.append(f"{tag}: url がYouTube以外 ({e['url']})")
        key = (e.get("date"), e.get("name"))
        if key in seen:
            errors.append(f"{tag}: 同一日付+同名の重複")
        seen.add(key)
        out.append(e)
    return out, errors

# ══════════ 本体 ══════════

def run(cmd, **kw):
    return subprocess.run(cmd, cwd=SITE_REPO, text=True,
                          capture_output=True, **kw)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # 1. 読み出し(read-only接続。書き込みは物理的に不可)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(QUERY)]
    con.close()

    if not rows:
        print("承認済みの星座がありません。終了します。")
        return 0

    # 2. 検証
    entries, errors = validate(rows)
    if errors:
        print("✗ 検証エラー。エクスポートを中止します:")
        for e in errors:
            print("   " + e)
        return 1

    # 3. 書き出し(決定論的: ソート・整形固定 → 無変更なら差分ゼロ)
    payload = json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
    target = SITE_REPO / JSON_NAME
    old = target.read_text(encoding="utf-8") if target.exists() else ""

    if payload == old:
        # ファイルは最新だが、前回commitに失敗して未コミットのまま残っている場合を救う
        r = run(["git", "status", "--porcelain", JSON_NAME])
        if r.stdout.strip():
            print("entries.json は最新ですが、未コミットの変更が残っています。")
            if not args.dry_run and input("commit & push しますか? [y/N] ").strip().lower() == "y":
                run(["git", "add", JSON_NAME])
                run(["git", "commit", "-m", "星座帳更新"])
                r = run(["git", "push"])
                print("✓ push しました。" if r.returncode == 0 else "✗ push失敗: " + r.stderr.strip())
        else:
            print("entries.json に変更はありません。")
        return 0

    print(f"── エクスポート内容({len(entries)}件)──")
    old_keys = {(e.get("date"), e.get("name"))
                for e in (json.loads(old) if old else [])}
    new_items = [e for e in entries
                 if (e["date"], e["name"]) not in old_keys]
    for e in new_items:
        vod = " (配信リンクあり)" if "url" in e else ""
        print(f"  + {e['date']}  {e['name']}  星{len(e['hoshi'])}{vod}")
        print(f"      {e['diary'][:40]}{'…' if len(e['diary'])>40 else ''}")
    removed = len(old_keys) - (len(entries) - len(new_items))
    if removed > 0:
        print(f"  - 削除/変更: {removed}件(entries.json 側と要確認)")

    if args.dry_run:
        print("(dry-run: ファイルもgitも触っていません)")
        return 0

    # 4. 人間の確認(ここは自動化しない)
    ans = input("この内容で公開しますか? [y/N] ").strip().lower()
    if ans != "y":
        print("中止しました。")
        return 0

    target.write_text(payload, encoding="utf-8")

    # 5. commit & push
    run(["git", "add", JSON_NAME])
    names = "、".join(e["name"] for e in new_items) or "更新"
    r = run(["git", "commit", "-m", f"星座追加: {names}"])
    if r.returncode != 0:
        print("✗ commit失敗:", r.stderr.strip()); return 1
    r = run(["git", "push"])
    if r.returncode != 0:
        print("✗ push失敗:", r.stderr.strip())
        print("  (commitは済んでいるので、後で git push だけやり直せます)")
        return 1

    print(f"✓ 公開しました({len(new_items)}件追加)。数十秒でサイトに反映されます。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
