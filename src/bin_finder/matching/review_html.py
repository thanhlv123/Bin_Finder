"""Portable Vietnamese review page with escaped markup and HTTPS-only media."""
import html
import json
from urllib.parse import urlsplit


def _e(value):
    return html.escape(str(value or ''), quote=True)


def _url(value):
    try:
        parts = urlsplit(value or '')
        if parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password:
            return _e(value)
        return ''
    except ValueError:
        return ''


_CSS = """
body{font:16px system-ui;background:#14202c;color:#eee;margin:24px}
section{margin:24px 0;padding:18px;background:#213243}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
article{padding:12px;border:2px solid #526779;border-radius:8px}
article.selected{border-color:#55ddaa}
video,img{width:100%;height:180px;object-fit:contain}
button{padding:8px;cursor:pointer}
a{color:#8ce}
p{overflow-wrap:anywhere}
.badge{color:#7fd}

"""

_SCRIPT = """
function refresh() {
    document.querySelectorAll('section').forEach(section => {
        const decision = decisions[section.dataset.cue];
        section.querySelectorAll('article').forEach(card => {
            card.classList.toggle('selected', card.dataset.source === decision.source_id);
        });
        section.hidden = document.querySelector('#filter').checked
            && section.dataset.status !== 'needs_review';
    });
}
document.addEventListener('click', event => {
    const button = event.target.closest('button[data-action]');
    if (!button) {
        return;
    }
    const section = button.closest('section');
    const card = button.closest('article');
    const action = button.dataset.action;
    decisions[section.dataset.cue] = {
        source_id: action === 'clear' ? null : card.dataset.source,
        lock: action === 'lock'
    };
    let status = 'manual';
    let badge = 'Chọn tay';
    if (action === 'clear') {
        status = 'needs_review';
        badge = 'Cần duyệt';
    } else if (action === 'lock') {
        status = 'locked';
        badge = 'Đã khóa';
    }
    section.dataset.status = status;
    section.querySelector('.badge').textContent = badge;
    refresh();
});

document.querySelector('#filter').onchange = refresh;

document.querySelectorAll('video').forEach(video => {
    video.onmouseenter = () => video.play().catch(() => {});
    video.onmouseleave = () => video.pause();
});

document.querySelector('#download').onclick = () => {
    const content = JSON.stringify({version: 1, decisions}, null, 2);
    const downloadUrl = URL.createObjectURL(new Blob([content], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = 'decisions.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
};
refresh();

"""


def _card(row):
    poster = _url(row['thumbnail_url'])
    preview = _url(row['preview_url'])
    if preview:
        media = (
            f'<video src="{preview}" poster="{poster}" muted loop '
            'preload="none" controls></video>'
        )
    elif poster:
        media = f'<img src="{poster}" loading="lazy" alt="Thumbnail">'
    else:
        media = '<p>Không có ảnh</p>'
    verdict = row['vlm']
    reasons = '; '.join(row['reasons'])
    if verdict:
        reasons += '; ' + verdict['reason']
    license_name = (row.get('license') or {}).get('license_name', '')
    visual_score = verdict['score'] if verdict else 'Chưa kiểm tra'
    return (
        f'<article data-source="{_e(row["source_id"])}">{media}<h3>{_e(row["title"])}</h3>'
        f'<p>Text: {row["text_score"]:.2f} · VLM: {_e(visual_score)} '
        f'· Tổng: {row["final_score"]:.2f}</p>'
        f'<p>{_e(reasons)}</p><p>{_e(row["provider"])} · {_e(license_name)}</p>'
        f'<a href="{_url(row["source_url"])}" target="_blank" rel="noopener noreferrer">Nguồn</a> '
        '<button data-action="choose">Chọn</button> <button data-action="lock">Khóa</button></article>'
    )


def _cue_block(cue):
    badges = {
        'auto_selected': 'AI đã chọn',
        'needs_review': 'Cần duyệt',
        'manual': 'Chọn tay',
        'locked': 'Đã khóa',
    }
    cards = ''.join(_card(row) for row in cue['ranked'])
    return (
        f'<section data-cue="{_e(cue["cue_id"])}" data-status="{_e(cue["status"])}">'
        f'<h2>{_e(cue["cue_id"])} · {_e(cue["text"])}</h2>'
        f'<strong class="badge">{badges[cue["status"]]}</strong> '
        f'· Độ tin cậy: {cue["confidence"]:.0%}'
        f'<p>{_e(", ".join(cue["flags"]))}</p><button data-action="clear">Bỏ chọn</button>'
        f'<div class="grid">{cards}</div></section>'
    )


def render_review_html(selection_plan):
    initial = {
        cue['cue_id']: {
            'source_id': cue['selected_source_id'],
            'lock': cue['status'] == 'locked',
        }
        for cue in selection_plan.cues
    }
    data = json.dumps(initial, ensure_ascii=True)
    data = data.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    blocks = ''.join(_cue_block(cue) for cue in selection_plan.cues)
    return (
        '<!doctype html><html lang="vi"><meta charset="utf-8"><title>Duyệt footage</title>'
        f'<style>{_CSS}</style>'
        '<h1>Duyệt và chọn footage</h1><label><input id="filter" type="checkbox">'
        'Chỉ cue cần duyệt</label> <button id="download">Tải decisions.json</button>'
        + blocks + '<script>const decisions=' + data + ';' + _SCRIPT + '</script></html>'
    )
