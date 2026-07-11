-- 値下げ処理の履歴（アイテム 1 件の処理毎に 1 行）
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,               -- ISO 8601
    profile TEXT NOT NULL,
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    old_price INTEGER NOT NULL,     -- 処理前の表示価格（送料込み）
    new_price INTEGER,              -- 値下げ後の表示価格（送料込み）。値下げしなかった場合は NULL
    favorite INTEGER NOT NULL,
    view INTEGER NOT NULL,
    action TEXT NOT NULL            -- ItemAction.value
);

CREATE INDEX IF NOT EXISTS idx_price_history_profile_item
    ON price_history (profile, item_id);

-- 前回実行時に出品一覧に存在したアイテム（売却検知用、実行毎に全置換）
CREATE TABLE IF NOT EXISTS item_snapshot (
    profile TEXT NOT NULL,
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    price INTEGER NOT NULL,
    favorite INTEGER NOT NULL,
    view INTEGER NOT NULL,
    seen_at TEXT NOT NULL,          -- ISO 8601
    PRIMARY KEY (profile, item_id)
);
