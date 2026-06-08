"""
figMap2 v2: 業種別省別choropleth切り替え注入スクリプト
sector_prov_data.json のデータを使い、updatemenusを更新する。
Baidu APIデータも同じJSON形式で渡せば動作する。
"""
import json, re, shutil

DATA_FILE = r'C:\tmp\sector_prov_data.json'
HTML_FILE = r'C:\Users\jin_z\Desktop\BaiduSyncdisk\0. 研究\10.0 成果\1.0 金のプレゼン\2017‐2026金融勉強会\20260609\中国ETSの発展と展望_v3.html'
BAK_FILE  = HTML_FILE + '.bak_v2_inject'

with open(DATA_FILE, encoding='utf-8') as f:
    data = json.load(f)

prov_order = data['prov_order']  # 31省（trace4と同順）
sector_data = data['sector_data']  # {'発電': [...], 'セメント': [...], ...}
trace4_total = [int(data['trace4'].get(p, 0)) for p in prov_order]

# trace4のtext/customdata/marker.sizeを生成
def make_trace4_data(prov_counts, label):
    """
    prov_counts: 31省のカウント配列
    label: 'ラベル' (trace4のtextに使用)
    """
    # trace4のtext形式: "省名 N" (上位15省のみ表示、残りは空)
    sorted_pairs = sorted(zip(prov_order, prov_counts), key=lambda x: -x[1])
    text_vals = []
    for prov, cnt in zip(prov_order, prov_counts):
        # 省名（末尾「省」除く）
        short = prov.replace('省', '')
        text_vals.append(f'{short} {cnt}' if cnt > 0 else '')

    customdata_vals = [f'{p} {label} {c}' for p, c in zip(prov_order, prov_counts)]
    # marker.size: trace4の元と同じスケーリング方法（元は施設数に比例）
    # 元のtrace4を読み取ってスケールを確認
    max_total = max(trace4_total)
    max_this = max(prov_counts) if max(prov_counts) > 0 else 1
    # 元のサイズ範囲を維持（最大値を正規化）
    sizes = [max(3, int(c / max_total * 60)) for c in prov_counts]
    return text_vals, customdata_vals, sizes

# 業種ごとのrestyle引数（trace[4]向け）
sector_map = {
    '全業種': (trace4_total, '施設数'),
    '発電': (sector_data['発電'], '発電施設数'),
    '鉄鋼': (sector_data['鉄鋼'], '鉄鋼施設数'),
    'セメント': (sector_data['セメント'], 'セメント施設数'),
    'アルミ冶金': (sector_data['アルミ冶金'], 'アルミ冶金施設数'),
}

# traceのvisible設定（trace順: [発電,セメント,鉄鋼,アルミ冶金,省別施設数]）
visible_map = {
    '全業種':   [True,  True,  True,  True,  True],
    '発電':     [True,  False, False, False, True],
    '鉄鋼':     [False, False, True,  False, True],
    'セメント': [False, True,  False, False, True],
    'アルミ冶金':[False, False, False, True,  True],
}

# updatemenusのbuttonsを生成
buttons = []
for label, (counts, desc) in sector_map.items():
    texts, cdatas, sizes = make_trace4_data(counts, desc)
    btn = {
        'label': label,
        'method': 'update',
        'args': [
            {
                'visible': visible_map[label],
                'text': [None, None, None, None, texts],
                'customdata': [None, None, None, None, cdatas],
                'marker.size': [None, None, None, None, sizes],
            }
        ]
    }
    buttons.append(btn)

new_updatemenus = [{
    'type': 'buttons',
    'direction': 'right',
    'x': 0.01,
    'y': 1.06,
    'xanchor': 'left',
    'yanchor': 'top',
    'bgcolor': 'rgba(15,35,60,0.85)',
    'bordercolor': '#2a6496',
    'borderwidth': 1,
    'font': {'color': '#cfe0f0', 'size': 12},
    'buttons': buttons
}]

print('buttons生成完了:', len(buttons), '個')
print('サンプル(発電) text[:3]:', buttons[1]['args'][0]['text'][4][:3])
print('サンプル(発電) sizes[:3]:', buttons[1]['args'][0]['marker.size'][4][:3])

# HTML読み込み・updatemenus部分を置換
with open(HTML_FILE, encoding='utf-8') as f:
    content = f.read()

# 現在のupdatemenus文字列を探して置換
old_um_start = content.find(', "updatemenus": [')
if old_um_start < 0:
    print('ERROR: updatemenus not found')
    exit(1)

# updatemenusの終端を探す（}]},{displayModeBar）
search_from = old_um_start + len(', "updatemenus": [')
# 対応する閉じ括弧を探す
depth = 0
i = old_um_start + len(', "updatemenus": ')
while i < len(content):
    if content[i] == '[':
        depth += 1
    elif content[i] == ']':
        depth -= 1
        if depth == 0:
            old_um_end = i + 1
            break
    i += 1

old_um_str = content[old_um_start:old_um_end]
print(f'旧updatemenus長: {len(old_um_str)}')

new_um_str = ', "updatemenus": ' + json.dumps(new_updatemenus, ensure_ascii=False)
print(f'新updatemenus長: {len(new_um_str)}')

# バックアップ
shutil.copy2(HTML_FILE, BAK_FILE)
print(f'backup: {BAK_FILE}')

# 置換
new_content = content[:old_um_start] + new_um_str + content[old_um_end:]
with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f'SUCCESS: HTML updated ({len(content)} -> {len(new_content)} chars)')
