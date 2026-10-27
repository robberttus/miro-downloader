#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Miro Board Offline Downloader & Zelfstandige HTML Viewer Generator
==================================================================
Geïnspireerd door jolle/miro-export, volledig geautomatiseerd in Python
met Playwright + httpx (100% zonder AI-tussenkomst).

Gebruik:
  python miro_downloader.py
  of:
  python miro_downloader.py "https://miro.com/app/board/uXjVEakmNhM=/"
  python miro_downloader.py "https://miro.com/app/board/uXjVEakmNhM=/" --output-dir "./mijn_export"
"""

import argparse
import asyncio
import csv
import datetime
import html
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx
from playwright.async_api import async_playwright


def extract_board_id(url_or_id: str) -> str:
    """Haalt het Miro boardId uit een volledige Miro URL of geeft de ID terug."""
    s = url_or_id.strip()
    match = re.search(r"miro\.com/app/board/([^/?#]+)", s)
    if match:
        return match.group(1)
    # Als de gebruiker enkel de ID plakt (bijv. uXjVEakmNhM=)
    if re.match(r"^[A-Za-z0-9_=-]{8,24}$", s):
        return s
    raise ValueError(
        f"Kon geen geldig Miro board-ID vinden in: '{url_or_id}'. "
        "Verwacht formaat: https://miro.com/app/board/uXjVEakmNhM=/"
    )


def sanitize_filename(name: str) -> str:
    """Verwijdert ongeldige Windows-bestandstekens."""
    if not name:
        return "bestand"
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()
    return cleaned or "bestand"


def strip_html_tags(text: str) -> str:
    """Verwijdert HTML-tags en decodeert HTML-entities voor weergave."""
    if not text:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", str(text))
    return html.unescape(re.sub(r"\s+", " ", no_tags)).strip()


def build_viewer_html(board_data: dict) -> str:
    """Genereert het volledige offline interactieve board_viewer.html bestand."""
    json_str = json.dumps(board_data, ensure_ascii=False)
    title_escaped = html.escape(board_data.get("title") or "Miro Bord Export")
    n_images = board_data.get("counts", {}).get("images", 0)
    n_frames = board_data.get("counts", {}).get("frames", 0)

    return f'''<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_escaped} - Miro Bord Export</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body, html {{ width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #121417; color: #f0f2f5; }}
  
  #canvas-container {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; cursor: grab; user-select: none; }}
  #canvas-container.grabbing {{ cursor: grabbing; }}
  canvas {{ display: block; width: 100%; height: 100%; }}

  /* Top Bar */
  .top-bar {{
    position: absolute; top: 16px; left: 16px; right: 16px;
    display: flex; justify-content: space-between; align-items: center; pointer-events: none; z-index: 10;
  }}
  .title-card {{
    background: rgba(24, 28, 36, 0.88); backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px;
    padding: 10px 18px; pointer-events: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  }}
  .title-card h1 {{ font-size: 15px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }}
  .title-card .badge {{ background: #3b82f6; font-size: 11px; padding: 2px 7px; border-radius: 6px; font-weight: 600; }}
  .title-card p {{ font-size: 12px; color: #94a3b8; margin-top: 2px; }}

  /* Search & Controls */
  .search-box {{
    position: relative; pointer-events: auto; width: 340px;
  }}
  .search-box input {{
    width: 100%; background: rgba(24, 28, 36, 0.88); backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 10px;
    padding: 9px 14px 9px 36px; font-size: 13px; color: #fff; outline: none;
    box-shadow: 0 8px 24px rgba(0,0,0,0.3); transition: border-color 0.2s;
  }}
  .search-box input:focus {{ border-color: #3b82f6; }}
  .search-box svg {{ position: absolute; left: 11px; top: 10px; width: 16px; height: 16px; fill: #94a3b8; }}
  .search-results {{
    position: absolute; top: 42px; left: 0; right: 0; max-height: 380px; overflow-y: auto;
    background: #181c24; border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 10px;
    display: none; box-shadow: 0 12px 36px rgba(0,0,0,0.5); z-index: 100;
  }}
  .search-item {{
    padding: 10px 14px; font-size: 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    cursor: pointer; display: flex; flex-direction: column; gap: 2px;
  }}
  .search-item:hover {{ background: rgba(59, 130, 246, 0.2); }}
  .search-item .filename {{ font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .search-item .meta {{ color: #94a3b8; font-size: 11px; }}

  /* Toolbar */
  .toolbar {{
    position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
    display: flex; gap: 8px; background: rgba(24, 28, 36, 0.88); backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px;
    padding: 6px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); z-index: 10;
  }}
  .tool-btn {{
    background: transparent; border: none; color: #e2e8f0; width: 36px; height: 36px;
    border-radius: 8px; display: flex; align-items: center; justify-content: center;
    cursor: pointer; transition: background 0.15s, color 0.15s;
  }}
  .tool-btn:hover {{ background: rgba(255, 255, 255, 0.12); color: #fff; }}
  .tool-btn svg {{ width: 18px; height: 18px; fill: currentColor; }}
  .zoom-label {{ font-size: 12px; font-weight: 600; padding: 0 8px; display: flex; align-items: center; color: #94a3b8; }}

  /* Minimap */
  .minimap-card {{
    position: absolute; bottom: 20px; right: 20px; width: 220px; height: 130px;
    background: rgba(24, 28, 36, 0.9); backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 12px;
    overflow: hidden; box-shadow: 0 8px 32px rgba(0,0,0,0.5); z-index: 10;
  }}
  #minimap-canvas {{ width: 100%; height: 100%; display: block; }}
  .minimap-viewport {{
    position: absolute; border: 2px solid #3b82f6; background: rgba(59, 130, 246, 0.25);
    pointer-events: none; border-radius: 2px;
  }}

  /* Image Lightbox Modal */
  .modal-overlay {{
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.85); backdrop-filter: blur(8px);
    display: none; align-items: center; justify-content: center; z-index: 1000; padding: 24px;
  }}
  .modal-content {{
    background: #181c24; border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 16px;
    max-width: 90vw; max-height: 92vh; display: flex; flex-direction: column; overflow: hidden;
    box-shadow: 0 24px 64px rgba(0,0,0,0.7);
  }}
  .modal-header {{
    display: flex; justify-content: space-between; align-items: center; padding: 14px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1); background: #1f242d;
  }}
  .modal-header h3 {{ font-size: 14px; font-weight: 600; color: #fff; max-width: 70vw; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .modal-actions {{ display: flex; gap: 10px; align-items: center; }}
  .btn-open {{
    background: #3b82f6; color: #fff; text-decoration: none; padding: 6px 14px; border-radius: 8px;
    font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; transition: background 0.2s;
  }}
  .btn-open:hover {{ background: #2563eb; }}
  .btn-close {{
    background: transparent; border: none; color: #94a3b8; font-size: 24px; line-height: 1; cursor: pointer; padding: 0 4px;
  }}
  .btn-close:hover {{ color: #fff; }}
  .modal-body {{
    flex: 1; overflow: auto; display: flex; align-items: center; justify-content: center; padding: 20px; background: #0f1217;
  }}
  .modal-body img {{ max-width: 100%; max-height: 72vh; object-fit: contain; border-radius: 4px; box-shadow: 0 12px 32px rgba(0,0,0,0.5); }}
  .modal-footer {{
    padding: 10px 20px; background: #181c24; border-top: 1px solid rgba(255, 255, 255, 0.08);
    display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8;
  }}
</style>
</head>
<body>

<div id="canvas-container">
  <canvas id="board-canvas"></canvas>
</div>

<div class="top-bar">
  <div class="title-card">
    <h1>{title_escaped} <span class="badge">Miro Export</span></h1>
    <p>{n_images} Afbeeldingen &amp; Documenten &bull; {n_frames} Kaders &bull; Volledig lokaal &amp; interactief</p>
  </div>
  <div class="search-box">
    <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
    <input type="text" id="search-input" placeholder="Zoek student, bestand of kader (bijv. Z6, Simon, Elena)...">
    <div class="search-results" id="search-results"></div>
  </div>
</div>

<div class="toolbar">
  <button class="tool-btn" id="btn-zoom-in" title="Inzoomen">
    <svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
  </button>
  <span class="zoom-label" id="zoom-percent">100%</span>
  <button class="tool-btn" id="btn-zoom-out" title="Uitzoomen">
    <svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14v2z"/></svg>
  </button>
  <button class="tool-btn" id="btn-fit" title="Volledig bord tonen (Fit)">
    <svg viewBox="0 0 24 24"><path d="M15 3l2.3 2.3-2.89 2.87 1.42 1.42L18.7 6.7 21 9V3h-6zM3 9l2.3-2.3 2.87 2.89 1.42-1.42L6.7 5.3 9 3H3v6zm6 12l-2.3-2.3 2.89-2.87-1.42-1.42L5.3 17.3 3 15v6h6zm12-6l-2.3 2.3-2.87-2.89-1.42 1.42 2.89 2.87L15 21h6v-6z"/></svg>
  </button>
</div>

<div class="minimap-card">
  <canvas id="minimap-canvas"></canvas>
  <div class="minimap-viewport" id="minimap-vp"></div>
</div>

<div class="modal-overlay" id="modal-overlay">
  <div class="modal-content">
    <div class="modal-header">
      <h3 id="modal-filename">Bestand</h3>
      <div class="modal-actions">
        <a href="#" target="_blank" class="btn-open" id="modal-open-btn">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>
          Open Origineel Bestand
        </a>
        <button class="btn-close" id="modal-close-btn">&times;</button>
      </div>
    </div>
    <div class="modal-body" id="modal-body">
      <img src="" id="modal-img" alt="">
    </div>
    <div class="modal-footer">
      <span id="modal-dimensions">-</span>
      <span id="modal-filesize">-</span>
    </div>
  </div>
</div>

<script>
window.BOARD_DATA = {json_str};

(function() {{
  const data = window.BOARD_DATA;
  const canvas = document.getElementById('board-canvas');
  const ctx = canvas.getContext('2d');
  const container = document.getElementById('canvas-container');
  const zoomPercentEl = document.getElementById('zoom-percent');
  const minimapCanvas = document.getElementById('minimap-canvas');
  const minimapCtx = minimapCanvas.getContext('2d');
  const minimapVp = document.getElementById('minimap-vp');

  let width = window.innerWidth;
  let height = window.innerHeight;
  let dpr = window.devicePixelRatio || 1;

  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;

  let highlightItem = null;
  let highlightTimer = null;

  const imageCache = new Map();

  function resize() {{
    width = window.innerWidth;
    height = window.innerHeight;
    dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.scale(dpr, dpr);

    minimapCanvas.width = 220 * dpr;
    minimapCanvas.height = 130 * dpr;
    minimapCtx.scale(dpr, dpr);

    draw();
  }}
  window.addEventListener('resize', resize);

  function zoomToFit() {{
    const b = data.bounds;
    const padding = 100;
    const scaleX = (width - padding * 2) / (b.width || 1000);
    const scaleY = (height - padding * 2) / (b.height || 1000);
    scale = Math.min(scaleX, scaleY);
    offsetX = (width - b.width * scale) / 2 - b.minX * scale;
    offsetY = (height - b.height * scale) / 2 - b.minY * scale;
    draw();
  }}

  function getImage(thumbPath) {{
    if (imageCache.has(thumbPath)) {{
      return imageCache.get(thumbPath);
    }}
    const img = new Image();
    img.src = 'thumbnails/' + thumbPath;
    img.onload = () => draw();
    imageCache.set(thumbPath, img);
    return img;
  }}

  function worldToScreen(wx, wy) {{
    return {{ x: wx * scale + offsetX, y: wy * scale + offsetY }};
  }}
  function screenToWorld(sx, sy) {{
    return {{ x: (sx - offsetX) / scale, y: (sy - offsetY) / scale }};
  }}

  function draw() {{
    ctx.clearRect(0, 0, width, height);

    ctx.save();
    ctx.fillStyle = '#121417';
    ctx.fillRect(0, 0, width, height);

    const b = data.bounds;
    const p1 = worldToScreen(b.minX - 80, b.minY - 80);
    const p2 = worldToScreen(b.maxX + 80, b.maxY + 80);
    ctx.fillStyle = '#181c22';
    ctx.fillRect(p1.x, p1.y, p2.x - p1.x, p2.y - p1.y);
    ctx.strokeStyle = '#272e3b';
    ctx.lineWidth = 1;
    ctx.strokeRect(p1.x, p1.y, p2.x - p1.x, p2.y - p1.y);

    // 1. Frames
    for (const f of data.frames || []) {{
      const sp = worldToScreen(f.x, f.y);
      const sw = f.width * scale;
      const sh = f.height * scale;

      if (sp.x + sw < 0 || sp.x > width || sp.y + sh < 0 || sp.y > height) continue;

      if (!f.parentId) {{
        ctx.fillStyle = 'rgba(255, 255, 255, 0.03)';
        ctx.fillRect(sp.x, sp.y, sw, sh);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        ctx.lineWidth = Math.max(1, 1.5 * scale);
        ctx.strokeRect(sp.x, sp.y, sw, sh);

        if (f.title) {{
          ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
          ctx.font = `bold ${{Math.max(11, 28 * scale)}}px sans-serif`;
          ctx.fillText(f.title, sp.x + 8, sp.y - 6);
        }}
      }} else {{
        ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
        ctx.fillRect(sp.x, sp.y, sw, sh);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 1;
        ctx.strokeRect(sp.x, sp.y, sw, sh);
      }}
    }}

    // 2. Shapes (Headers)
    for (const s of data.shapes || []) {{
      const sp = worldToScreen(s.x, s.y);
      const sw = s.width * scale;
      const sh = s.height * scale;

      if (sp.x + sw < 0 || sp.x > width || sp.y + sh < 0 || sp.y > height) continue;

      ctx.fillStyle = '#1e242d';
      ctx.fillRect(sp.x, sp.y, sw, sh);
      ctx.strokeStyle = '#3b82f6';
      ctx.lineWidth = 2;
      ctx.strokeRect(sp.x, sp.y, sw, sh);

      const cleanText = (s.content || '').replace(/<[^>]+>/g, '').trim();
      ctx.fillStyle = '#ffffff';
      ctx.font = `bold ${{Math.max(12, 34 * scale)}}px sans-serif`;
      ctx.fillText(cleanText, sp.x + 16, sp.y + sh / 2 + (12 * scale));
    }}

    // 3. Stickies
    for (const sn of data.stickies || []) {{
      const sp = worldToScreen(sn.x, sn.y);
      const sw = sn.width * scale;
      const sh = sn.height * scale;

      if (sp.x + sw < 0 || sp.x > width || sp.y + sh < 0 || sp.y > height) continue;

      ctx.fillStyle = '#fef08a';
      ctx.fillRect(sp.x, sp.y, sw, sh);
      ctx.strokeStyle = '#fde047';
      ctx.lineWidth = 1;
      ctx.strokeRect(sp.x, sp.y, sw, sh);

      ctx.fillStyle = '#713f12';
      ctx.font = `bold ${{Math.max(10, 24 * scale)}}px sans-serif`;
      ctx.fillText(sn.content || '', sp.x + 10, sp.y + sh / 2 + (8 * scale));
    }}

    // 3b. Texts
    for (const t of data.texts || []) {{
      const sp = worldToScreen(t.x, t.y);
      const sw = (t.width || 200) * scale;
      const sh = (t.height || 40) * scale;

      if (sp.x + sw < 0 || sp.x > width || sp.y + sh < 0 || sp.y > height) continue;

      const cleanText = (t.content || '').replace(/<[^>]+>/g, '').trim();
      if (cleanText) {{
        ctx.fillStyle = '#e2e8f0';
        ctx.font = `${{Math.max(10, 20 * scale)}}px sans-serif`;
        ctx.fillText(cleanText, sp.x, sp.y + (18 * scale));
      }}
    }}

    // 4. Images
    for (const imgItem of data.images || []) {{
      const sp = worldToScreen(imgItem.x, imgItem.y);
      const sw = imgItem.width * scale;
      const sh = imgItem.height * scale;

      if (sp.x + sw < 0 || sp.x > width || sp.y + sh < 0 || sp.y > height) continue;

      const img = getImage(imgItem.thumbnail_file);
      if (img.complete && img.naturalWidth > 0) {{
        ctx.drawImage(img, sp.x, sp.y, sw, sh);
      }} else {{
        ctx.fillStyle = '#2d3748';
        ctx.fillRect(sp.x, sp.y, sw, sh);
      }}

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
      ctx.lineWidth = 1;
      ctx.strokeRect(sp.x, sp.y, sw, sh);
    }}

    // 5. Highlight Pulse
    if (highlightItem) {{
      const sp = worldToScreen(highlightItem.x, highlightItem.y);
      const sw = highlightItem.width * scale;
      const sh = highlightItem.height * scale;
      ctx.strokeStyle = '#3b82f6';
      ctx.lineWidth = 4;
      ctx.strokeRect(sp.x - 4, sp.y - 4, sw + 8, sh + 8);
    }}

    ctx.restore();

    zoomPercentEl.textContent = Math.round(scale * 100) + '%';
    drawMinimap();
  }}

  function drawMinimap() {{
    minimapCtx.clearRect(0, 0, 220, 130);
    const b = data.bounds;
    const pad = 10;
    const mScaleX = (220 - pad * 2) / (b.width || 1000);
    const mScaleY = (130 - pad * 2) / (b.height || 1000);
    const mScale = Math.min(mScaleX, mScaleY);

    const mOffsetX = (220 - b.width * mScale) / 2 - b.minX * mScale;
    const mOffsetY = (130 - b.height * mScale) / 2 - b.minY * mScale;

    minimapCtx.fillStyle = 'rgba(255, 255, 255, 0.15)';
    for (const f of data.frames || []) {{
      if (!f.parentId) {{
        const mx = f.x * mScale + mOffsetX;
        const my = f.y * mScale + mOffsetY;
        const mw = f.width * mScale;
        const mh = f.height * mScale;
        minimapCtx.fillRect(mx, my, mw, mh);
      }}
    }}

    minimapCtx.fillStyle = '#3b82f6';
    for (const im of data.images || []) {{
      const mx = im.x * mScale + mOffsetX;
      const my = im.y * mScale + mOffsetY;
      const mw = Math.max(1, im.width * mScale);
      const mh = Math.max(1, im.height * mScale);
      minimapCtx.fillRect(mx, my, mw, mh);
    }}

    const vpWorldTopLeft = screenToWorld(0, 0);
    const vpWorldBottomRight = screenToWorld(width, height);
    const vx = vpWorldTopLeft.x * mScale + mOffsetX;
    const vy = vpWorldTopLeft.y * mScale + mOffsetY;
    const vw = (vpWorldBottomRight.x - vpWorldTopLeft.x) * mScale;
    const vh = (vpWorldBottomRight.y - vpWorldTopLeft.y) * mScale;

    minimapVp.style.left = Math.max(0, vx) + 'px';
    minimapVp.style.top = Math.max(0, vy) + 'px';
    minimapVp.style.width = Math.min(220, vw) + 'px';
    minimapVp.style.height = Math.min(130, vh) + 'px';
  }}

  container.addEventListener('mousedown', (e) => {{
    if (e.button !== 0 && e.button !== 1) return;
    isDragging = true;
    dragStartX = e.clientX - offsetX;
    dragStartY = e.clientY - offsetY;
    container.classList.add('grabbing');
  }});

  window.addEventListener('mousemove', (e) => {{
    if (!isDragging) return;
    offsetX = e.clientX - dragStartX;
    offsetY = e.clientY - dragStartY;
    draw();
  }});

  window.addEventListener('mouseup', () => {{
    if (isDragging) {{
      isDragging = false;
      container.classList.remove('grabbing');
    }}
  }});

  container.addEventListener('wheel', (e) => {{
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const mouseX = e.clientX;
    const mouseY = e.clientY;

    const newScale = Math.min(Math.max(scale * zoomFactor, 0.01), 6.0);
    offsetX = mouseX - (mouseX - offsetX) * (newScale / scale);
    offsetY = mouseY - (mouseY - offsetY) * (newScale / scale);
    scale = newScale;

    draw();
  }}, {{ passive: false }});

  container.addEventListener('click', (e) => {{
    const clickWorld = screenToWorld(e.clientX, e.clientY);
    let clicked = null;
    for (let i = (data.images || []).length - 1; i >= 0; i--) {{
      const im = data.images[i];
      if (clickWorld.x >= im.x && clickWorld.x <= im.x + im.width &&
          clickWorld.y >= im.y && clickWorld.y <= im.y + im.height) {{
        clicked = im;
        break;
      }}
    }}
    if (clicked) {{
      openModal(clicked);
    }}
  }});

  const modal = document.getElementById('modal-overlay');
  const modalImg = document.getElementById('modal-img');
  const modalFilename = document.getElementById('modal-filename');
  const modalOpenBtn = document.getElementById('modal-open-btn');
  const modalDim = document.getElementById('modal-dimensions');
  const modalSize = document.getElementById('modal-filesize');
  const modalClose = document.getElementById('modal-close-btn');

  function openModal(item) {{
    modalFilename.textContent = item.filename;
    modalOpenBtn.href = 'images/' + item.original_file;
    modalDim.textContent = item.naturalWidth && item.naturalHeight ? `${{item.naturalWidth}} \u00d7 ${{item.naturalHeight}} px` : `${{Math.round(item.width)}} \u00d7 ${{Math.round(item.height)}} pt`;
    modalSize.textContent = item.filesize ? (item.filesize / (1024*1024)).toFixed(2) + ' MB' : '';

    if ((item.extension || '').toLowerCase() === 'pdf') {{
      modalImg.src = 'thumbnails/' + item.thumbnail_file;
      modalOpenBtn.textContent = 'Open Originele PDF';
    }} else {{
      modalImg.src = 'images/' + item.original_file;
      modalOpenBtn.textContent = 'Open Originele Afbeelding';
    }}
    modal.style.display = 'flex';
  }}

  function closeModal() {{
    modal.style.display = 'none';
    modalImg.src = '';
  }}
  modalClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {{
    if (e.target === modal) closeModal();
  }});
  window.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape') closeModal();
  }});

  const searchInput = document.getElementById('search-input');
  const searchResults = document.getElementById('search-results');

  searchInput.addEventListener('input', () => {{
    const q = searchInput.value.trim().toLowerCase();
    if (!q) {{
      searchResults.style.display = 'none';
      return;
    }}

    const matches = [];

    for (const im of data.images || []) {{
      if ((im.filename || '').toLowerCase().includes(q)) {{
        matches.push({{ type: 'Afbeelding/Doc', title: im.filename, item: im }});
        if (matches.length >= 25) break;
      }}
    }}

    for (const f of data.frames || []) {{
      if (f.title && f.title.toLowerCase().includes(q)) {{
        matches.push({{ type: 'Kader', title: f.title, item: f }});
        if (matches.length >= 25) break;
      }}
    }}

    for (const s of data.stickies || []) {{
      if (s.content && s.content.toLowerCase().includes(q)) {{
        matches.push({{ type: 'Post-it', title: s.content, item: s }});
        if (matches.length >= 25) break;
      }}
    }}

    if (matches.length === 0) {{
      searchResults.innerHTML = '<div class="search-item"><span class="meta">Geen resultaten gevonden</span></div>';
    }} else {{
      searchResults.innerHTML = matches.map((m, idx) => `
        <div class="search-item" data-idx="${{idx}}">
          <span class="filename">${{m.title}}</span>
          <span class="meta">${{m.type}}</span>
        </div>
      `).join('');

      searchResults.querySelectorAll('.search-item').forEach((el, idx) => {{
        el.addEventListener('click', () => {{
          const match = matches[idx];
          focusOnItem(match.item);
          searchResults.style.display = 'none';
        }});
      }});
    }}
    searchResults.style.display = 'block';
  }});

  function focusOnItem(item) {{
    const targetScale = Math.min(width / ((item.width || 200) * 2.5), 2.0);
    scale = Math.max(targetScale, 0.4);
    const itemCenterX = item.x + (item.width || 200) / 2;
    const itemCenterY = item.y + (item.height || 200) / 2;
    offsetX = width / 2 - itemCenterX * scale;
    offsetY = height / 2 - itemCenterY * scale;

    highlightItem = item;
    draw();

    clearTimeout(highlightTimer);
    highlightTimer = setTimeout(() => {{
      highlightItem = null;
      draw();
    }}, 3000);
  }}

  document.getElementById('btn-zoom-in').addEventListener('click', () => {{
    scale = Math.min(scale * 1.3, 6.0);
    draw();
  }});
  document.getElementById('btn-zoom-out').addEventListener('click', () => {{
    scale = Math.max(scale / 1.3, 0.01);
    draw();
  }});
  document.getElementById('btn-fit').addEventListener('click', () => {{
    zoomToFit();
  }});

  resize();
  zoomToFit();
}})();
</script>
</body>
</html>'''


async def extract_miro_board_data(board_id: str) -> dict:
    """
    Opent het publieke Miro bord in een headless Chromium browser via Playwright,
    vangt alle /resources/batch/meta responses op én haalt alle objecten + coördinaten
    uit window.miro.board.get() en objectsRepository.getAllObjects().
    """
    board_url = f"https://miro.com/app/board/{board_id}/"
    print(f"[1/4] Miro bord openen in headless browser: {board_url}")

    resources_meta = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # Hook Object.prototype.resourceId om toegang te krijgen tot interne Miro canvas widgets
        await page.add_init_script("""
            window.__COMPONENTS = [];
            Object.defineProperty(Object.prototype, 'resourceId', {
                set: function(val) {
                    this._resourceId = val;
                    if (val && typeof val === 'string' && val.length > 5) {
                        window.__COMPONENTS.push(this);
                    }
                },
                get: function() {
                    return this._resourceId;
                },
                configurable: true
            });
        """)

        async def handle_response(response):
            if "/resources/batch/meta" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "id" in item:
                                resources_meta[str(item["id"])] = item
                except Exception:
                    pass

        page.on("response", handle_response)

        await page.goto(board_url, wait_until="domcontentloaded", timeout=90000)

        # Wacht tot window.miro.board beschikbaar is en objecten geladen zijn
        print("      Wachten tot het Miro canvas en de objecten geladen zijn...")
        for _ in range(30):
            await page.wait_for_timeout(1000)
            ready = await page.evaluate("""() => {
                return Boolean(
                    window.miro &&
                    window.miro.board &&
                    typeof window.miro.board.get === 'function'
                );
            }""")
            if ready:
                break

        # Geef Miro nog enkele seconden om alle initiële widgets en batch/meta calls te verwerken
        await page.wait_for_timeout(8000)

        raw_page_title = await page.title()
        board_title = re.sub(r"\s*-\s*Miro\s*$", "", raw_page_title).strip() or f"Miro_{board_id}"

        print(f"      Bord gevonden: '{board_title}'")
        print("      Alle objecten, kaders en exacte coördinaten uitlezen...")

        extracted = await page.evaluate("""async () => {
            const sdkItems = (window.miro && window.miro.board && window.miro.board.get)
                ? await window.miro.board.get()
                : [];

            let repoObjects = [];
            for (const comp of (window.__COMPONENTS || [])) {
                if (comp && comp.widget && comp.widget.objectsRepository &&
                    typeof comp.widget.objectsRepository.getAllObjects === 'function') {
                    const allObjs = comp.widget.objectsRepository.getAllObjects();
                    for (const o of allObjs) {
                        try {
                            const d = o.getData ? o.getData() : {};
                            if (d && d.resource && d.resource.id) {
                                repoObjects.push({
                                    id: String(o.id),
                                    type: String(o.type),
                                    bounds: o.bounds ? {
                                        x: o.bounds.x,
                                        y: o.bounds.y,
                                        width: o.bounds.width,
                                        height: o.bounds.height
                                    } : null,
                                    scale: o.scale || 1,
                                    rotation: o.rotation || 0,
                                    resource: {
                                        id: String(d.resource.id),
                                        boardId: d.resource.boardId,
                                        name: d.resource.name,
                                        width: d.resource.width,
                                        height: d.resource.height
                                    }
                                });
                            }
                        } catch (e) {}
                    }
                    break;
                }
            }

            return {
                sdkItems: sdkItems,
                repoObjects: repoObjects
            };
        }""")

        sdk_items = extracted.get("sdkItems", [])
        repo_objects = extracted.get("repoObjects", [])

        # Controleer of er resource IDs zijn waarvan de metadata nog niet via het netwerk is binnengekomen
        all_resource_ids = set(resources_meta.keys())
        for obj in repo_objects:
            res_id = str(obj.get("resource", {}).get("id", ""))
            if res_id:
                all_resource_ids.add(res_id)
        for item in sdk_items:
            if item.get("type") in ("image", "document", "preview"):
                all_resource_ids.add(str(item.get("id", "")))

        missing_ids = [rid for rid in all_resource_ids if rid and rid not in resources_meta]
        if missing_ids:
            print(f"      Aanvullende metadata ophalen voor {len(missing_ids)} bestanden...")
            for i in range(0, len(missing_ids), 50):
                batch = missing_ids[i : i + 50]
                batch_data = await page.evaluate(
                    """async ({ boardId, ids }) => {
                        try {
                            const url = `/api/v1/boards/${encodeURIComponent(boardId)}/resources/batch/meta?ids=${ids.join(',')}`;
                            const resp = await fetch(url, { credentials: 'include' });
                            if (resp.ok) {
                                return await resp.json();
                            }
                        } catch (e) {}
                        return [];
                    }""",
                    {"boardId": board_id, "ids": batch},
                )
                if isinstance(batch_data, list):
                    for item in batch_data:
                        if isinstance(item, dict) and "id" in item:
                            resources_meta[str(item["id"])] = item

        # Bewaar eventuele cookies uit de browser voor het downloaden
        cookies = await context.cookies()
        cookie_jar = {c["name"]: c["value"] for c in cookies}

        await browser.close()

    return {
        "board_id": board_id,
        "board_title": board_title,
        "sdk_items": sdk_items,
        "repo_objects": repo_objects,
        "resources_meta": resources_meta,
        "cookies": cookie_jar,
    }


async def download_all_resources(
    board_id: str,
    resources_meta: dict,
    cookies: dict,
    output_dir: Path,
) -> dict:
    """
    Downloadt alle hoge-resolutie originele bestanden (images/ & PDFs) én
    de LOD-thumbnails (thumbnails/) parallel via httpx.
    Geeft een resource_map dict terug.
    """
    images_dir = output_dir / "images"
    thumbs_dir = output_dir / "thumbnails"
    images_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    total = len(resources_meta)
    print(f"[2/4] {total} bestanden en thumbnails downloaden (hoge resolutie + previews)...")

    resource_map = {}
    semaphore = asyncio.Semaphore(12)
    completed = 0

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://miro.com/app/board/{board_id}/",
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=90.0,
        headers=headers,
        cookies=cookies,
    ) as client:

        async def process_resource(res_id: str, rdata: dict):
            nonlocal completed
            async with semaphore:
                raw_name = rdata.get("name") or f"resource_{res_id}"
                meta = rdata.get("meta") or {}
                ext = (meta.get("extension") or "jpg").lower()

                safe_name = sanitize_filename(raw_name)
                if not safe_name.lower().endswith(f".{ext}"):
                    safe_name = f"{safe_name}.{ext}"

                orig_filename = f"{res_id}_{safe_name}"
                thumb_filename = f"{res_id}.jpg"

                orig_path = images_dir / orig_filename
                thumb_path = thumbs_dir / thumb_filename

                download_urls = rdata.get("downloadUrls") or {}
                lod_url = (download_urls.get("lod") or {}).get("url")
                created_url = (download_urls.get("created") or {}).get("url")

                # 1. Download Thumbnail (LOD)
                if lod_url and not (thumb_path.exists() and thumb_path.stat().st_size > 0):
                    for attempt in range(3):
                        try:
                            resp = await client.get(lod_url)
                            if resp.status_code == 200 and len(resp.content) > 0:
                                thumb_path.write_bytes(resp.content)
                                break
                        except Exception:
                            await asyncio.sleep(1)

                # 2. Download Origineel bestand via /files/original endpoint
                if not (orig_path.exists() and orig_path.stat().st_size > 0):
                    orig_api_url = (
                        f"https://miro.com/api/v1/boards/{quote(board_id, safe='')}"
                        f"/resources/{res_id}/files/original"
                    )
                    downloaded = False
                    for attempt in range(3):
                        try:
                            resp = await client.get(orig_api_url)
                            if resp.status_code == 200 and len(resp.content) > 0:
                                orig_path.write_bytes(resp.content)
                                downloaded = True
                                break
                            elif resp.status_code == 404:
                                break
                        except Exception:
                            await asyncio.sleep(1.5)

                    # Fallback naar created_url of lod_url als /files/original niet beschikbaar is
                    if not downloaded:
                        fallback_url = created_url or lod_url
                        if fallback_url:
                            try:
                                resp = await client.get(fallback_url)
                                if resp.status_code == 200 and len(resp.content) > 0:
                                    orig_path.write_bytes(resp.content)
                            except Exception:
                                pass

                # Als thumbnail ontbrak maar origineel een afbeelding is, kopieer origineel als fallback
                if not thumb_path.exists() and orig_path.exists() and ext in ("jpg", "jpeg", "png", "webp"):
                    try:
                        thumb_path.write_bytes(orig_path.read_bytes())
                    except Exception:
                        pass

                resource_map[res_id] = {
                    "id": res_id,
                    "original_name": raw_name,
                    "extension": ext,
                    "original_file": orig_filename,
                    "thumbnail_file": thumb_filename,
                    "width": meta.get("width", 0),
                    "height": meta.get("height", 0),
                    "filesize": meta.get("filesize", 0),
                    "type": rdata.get("type", "imageWidget"),
                }

                completed += 1
                if completed % 25 == 0 or completed == total:
                    print(f"      Voortgang: {completed}/{total} bestanden gedownload...")

        tasks = [process_resource(str(rid), rdata) for rid, rdata in resources_meta.items()]
        if tasks:
            await asyncio.gather(*tasks)

    return resource_map


def build_board_structure(
    board_id: str,
    board_title: str,
    sdk_items: list,
    repo_objects: list,
    resource_map: dict,
) -> dict:
    """
    Combineert alle Miro items en berekent de exacte coördinaten voor
    frames, shapes, stickies, texts en images.
    """
    print("[3/4] Coördinaten en bord-layout berekenen...")

    # Map alle frames op ID zodat geneste frames (met parentId) hun absolute positie krijgen
    frames_by_id = {
        str(item["id"]): item
        for item in sdk_items
        if item.get("type") == "frame" and "id" in item
    }

    def get_item_top_left(item: dict) -> tuple[float, float]:
        w = float(item.get("width") or 0)
        h = float(item.get("height") or 0)
        x = float(item.get("x") or 0)
        y = float(item.get("y") or 0)
        parent_id = str(item.get("parentId")) if item.get("parentId") else None
        if parent_id and parent_id in frames_by_id:
            parent = frames_by_id[parent_id]
            px, py = get_item_top_left(parent)
            return px + x - w / 2.0, py + y - h / 2.0
        return x - w / 2.0, y - h / 2.0

    # 1. Frames
    frames_out = []
    for item in sdk_items:
        if item.get("type") == "frame":
            left, top = get_item_top_left(item)
            frames_out.append({
                "id": str(item.get("id")),
                "title": item.get("title") or "",
                "x": left,
                "y": top,
                "width": float(item.get("width") or 0),
                "height": float(item.get("height") or 0),
                "parentId": str(item["parentId"]) if item.get("parentId") else None,
                "fillColor": (item.get("style") or {}).get("fillColor", "#ffffff"),
            })

    # 2. Shapes
    shapes_out = []
    for item in sdk_items:
        if item.get("type") == "shape":
            left, top = get_item_top_left(item)
            shapes_out.append({
                "id": str(item.get("id")),
                "content": item.get("content") or "",
                "x": left,
                "y": top,
                "width": float(item.get("width") or 0),
                "height": float(item.get("height") or 0),
                "style": item.get("style") or {},
            })

    # 3. Sticky notes
    stickies_out = []
    for item in sdk_items:
        if item.get("type") == "sticky_note":
            left, top = get_item_top_left(item)
            stickies_out.append({
                "id": str(item.get("id")),
                "content": strip_html_tags(item.get("content") or ""),
                "x": left,
                "y": top,
                "width": float(item.get("width") or 0),
                "height": float(item.get("height") or 0),
                "fillColor": (item.get("style") or {}).get("fillColor", "light_yellow"),
            })

    # 4. Texts
    texts_out = []
    for item in sdk_items:
        if item.get("type") == "text":
            w = float(item.get("width") or 200)
            h = float(item.get("height") or 40)
            left, top = get_item_top_left({**item, "width": w, "height": h})
            texts_out.append({
                "id": str(item.get("id")),
                "content": item.get("content") or "",
                "x": left,
                "y": top,
                "width": w,
                "height": h,
                "scale": float(item.get("scale") or 1),
                "style": item.get("style") or {},
            })

    # 5. Images & Documenten
    images_out = []
    seen_ids = set()

    for obj in repo_objects:
        res = obj.get("resource") or {}
        res_id = str(res.get("id") or "")
        bounds = obj.get("bounds")
        if not res_id or not bounds or res_id not in resource_map:
            continue
        rm = resource_map[res_id]
        obj_id = str(obj.get("id") or res_id)
        seen_ids.add(obj_id)
        images_out.append({
            "id": obj_id,
            "resourceId": res_id,
            "filename": rm["original_name"],
            "extension": rm["extension"],
            "original_file": rm["original_file"],
            "thumbnail_file": rm["thumbnail_file"],
            "x": float(bounds["x"]),
            "y": float(bounds["y"]),
            "width": float(bounds["width"]),
            "height": float(bounds["height"]),
            "rotation": float(obj.get("rotation") or 0),
            "filesize": rm["filesize"],
            "naturalWidth": rm["width"],
            "naturalHeight": rm["height"],
        })

    # Fallback als bepaalde images/docs wel in sdk_items zitten maar niet in repo_objects
    for item in sdk_items:
        if item.get("type") in ("image", "document"):
            item_id = str(item.get("id") or "")
            if item_id in seen_ids or item_id not in resource_map:
                continue
            rm = resource_map[item_id]
            w = float(item.get("width") or rm["width"] or 200)
            h = float(item.get("height") or rm["height"] or 200)
            left, top = get_item_top_left({**item, "width": w, "height": h})
            images_out.append({
                "id": item_id,
                "resourceId": item_id,
                "filename": rm["original_name"],
                "extension": rm["extension"],
                "original_file": rm["original_file"],
                "thumbnail_file": rm["thumbnail_file"],
                "x": left,
                "y": top,
                "width": w,
                "height": h,
                "rotation": float(item.get("rotation") or 0),
                "filesize": rm["filesize"],
                "naturalWidth": rm["width"],
                "naturalHeight": rm["height"],
            })

    # Bereken totale bounding box van het bord
    all_elements = images_out + frames_out + shapes_out + stickies_out + texts_out
    if all_elements:
        min_x = min(el["x"] for el in all_elements)
        min_y = min(el["y"] for el in all_elements)
        max_x = max(el["x"] + el["width"] for el in all_elements)
        max_y = max(el["y"] + el["height"] for el in all_elements)
    else:
        min_x, min_y, max_x, max_y = 0.0, 0.0, 1920.0, 1080.0

    return {
        "title": board_title,
        "boardId": board_id,
        "bounds": {
            "minX": min_x,
            "minY": min_y,
            "maxX": max_x,
            "maxY": max_y,
            "width": max(1.0, max_x - min_x),
            "height": max(1.0, max_y - min_y),
        },
        "counts": {
            "images": len(images_out),
            "frames": len(frames_out),
            "shapes": len(shapes_out),
            "stickies": len(stickies_out),
            "texts": len(texts_out),
        },
        "images": images_out,
        "frames": frames_out,
        "shapes": shapes_out,
        "stickies": stickies_out,
        "texts": texts_out,
    }


def write_export_files_and_zip(
    output_dir: Path,
    board_data: dict,
    resource_map: dict,
    create_zip: bool = True,
) -> tuple[Path, Path | None]:
    """
    Schrijft board_data.json, resource_map.json, overzicht_studenten_en_bestanden.csv,
    README.md en board_viewer.html weg en verpakt alles in een .zip-bestand.
    """
    print("[4/4] Offline viewer, CSV-overzicht en ZIP-archief aanmaken...")

    # 1. board_data.json
    (output_dir / "board_data.json").write_text(
        json.dumps(board_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. resource_map.json
    (output_dir / "resource_map.json").write_text(
        json.dumps(resource_map, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3. overzicht_studenten_en_bestanden.csv
    csv_path = output_dir / "overzicht_studenten_en_bestanden.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "ID",
            "Bestandsnaam",
            "Extensie",
            "Bestandsgrootte (MB)",
            "Resolutie",
            "X-positie",
            "Y-positie",
            "Breedte",
            "Hoogte",
            "Pad naar Origineel",
        ])
        for im in sorted(board_data["images"], key=lambda x: (x.get("filename") or "").lower()):
            size_mb = round((im.get("filesize") or 0) / (1024 * 1024), 2) if im.get("filesize") else 0
            res_str = (
                f"{im['naturalWidth']}x{im['naturalHeight']}"
                if im.get("naturalWidth") and im.get("naturalHeight")
                else "-"
            )
            writer.writerow([
                im["id"],
                im["filename"],
                im["extension"],
                size_mb,
                res_str,
                round(im["x"], 1),
                round(im["y"], 1),
                round(im["width"], 1),
                round(im["height"], 1),
                f"images/{im['original_file']}",
            ])

    # 4. board_viewer.html
    viewer_path = output_dir / "board_viewer.html"
    viewer_path.write_text(build_viewer_html(board_data), encoding="utf-8")

    # 5. README.md
    counts = board_data["counts"]
    board_title = board_data["title"]
    board_id = board_data["boardId"]
    readme_content = f"""# Volledige Offline Export: {board_title}

Dit pakket bevat de **volledige export** van het publieke Miro-bord (`https://miro.com/app/board/{board_id}/`), inclusief alle originele hoge-resolutie bestanden en een interactieve lokale Miro-viewer die 100% offline werkt.

## 📂 Inhoud van deze map

1. **`board_viewer.html`** *(AANBEVOLEN)*
   - Dubbelklik op dit bestand om het volledige Miro-bord lokaal in je browser (Chrome, Edge, Firefox) te openen.
   - **Geen internet of server nodig**: werkt 100% offline.
   - **Zoekfunctie rechtsboven**: zoek op naam, nummer of bestandsnaam om direct naar de juiste plek op het bord te vliegen.
   - **Klik op een afbeelding of PDF**: opent een scherp voorbeeldvenster met een blauwe knop **"Open Origineel Bestand"** waarmee de originele PDF of hoge-resolutie foto direct wordt geopend.
   - **Minimap rechtsonder**: toont waar je je op het bord bevindt.

2. **`images/`** ({counts['images']} bestanden)
   - Bevat alle originele bestanden en documenten op volledige resolutie zoals geüpload naar Miro.

3. **`thumbnails/`** ({counts['images']} bestanden)
   - Bevat geoptimaliseerde weergave-afbeeldingen zodat de interactieve viewer vloeiend op 60 fps kan in- en uitzoomen.

4. **`overzicht_studenten_en_bestanden.csv`**
   - Een Excel-compatibel overzicht (puntkomma-gescheiden) van alle {counts['images']} bestanden met hun bestandsnaam, resolutie, bestandsgrootte, exacte X/Y-coördinaten op het bord en het pad naar het bestand.

5. **`board_data.json`**
   - De ruwe, gestructureerde data van het volledige Miro-bord ({counts['images']} afbeeldingen/PDF's, {counts['frames']} frames, {counts['shapes']} titelbalken, {counts['stickies']} post-its, {counts['texts']} teksten) met alle exacte coördinaten.
"""
    (output_dir / "README.md").write_text(readme_content, encoding="utf-8")

    # 6. Maak het .zip archief
    zip_path = None
    if create_zip:
        zip_path = output_dir.parent / f"{output_dir.name}.zip"
        print(f"      ZIP-bestand inpakken: {zip_path.name} ...")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for file_path in output_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(output_dir.parent)
                    zf.write(file_path, arcname)

    return viewer_path, zip_path


async def run_export(url_or_id: str, base_output_dir: Path | None = None, create_zip: bool = True):
    board_id = extract_board_id(url_or_id)
    extracted = await extract_miro_board_data(board_id)

    board_title = extracted["board_title"]
    safe_title = sanitize_filename(board_title)
    date_prefix = datetime.datetime.now().strftime("%Y%m%d")

    if base_output_dir is None:
        base_output_dir = Path.cwd() / "exports"
    base_output_dir.mkdir(parents=True, exist_ok=True)

    folder_name = f"{date_prefix} Export Miro - {safe_title}"
    output_dir = base_output_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    resource_map = await download_all_resources(
        board_id=board_id,
        resources_meta=extracted["resources_meta"],
        cookies=extracted["cookies"],
        output_dir=output_dir,
    )

    board_data = build_board_structure(
        board_id=board_id,
        board_title=board_title,
        sdk_items=extracted["sdk_items"],
        repo_objects=extracted["repo_objects"],
        resource_map=resource_map,
    )

    viewer_path, zip_path = write_export_files_and_zip(
        output_dir=output_dir,
        board_data=board_data,
        resource_map=resource_map,
        create_zip=create_zip,
    )

    counts = board_data["counts"]
    print("\n" + "=" * 68)
    print("VOLTOOID! Miro bord succesvol offline gedownload.")
    print("=" * 68)
    print(f"Bord titel       : {board_title}")
    print(f"Bestanden (HD)   : {counts['images']} afbeeldingen & PDF's")
    print(f"Kaders (Frames)  : {counts['frames']}")
    print(f"Post-its & Vormen: {counts['stickies']} post-its, {counts['shapes']} vormen")
    print(f"Export map       : {output_dir}")
    print(f"Offline Viewer   : {viewer_path}")
    if zip_path and zip_path.exists():
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"ZIP-bestand      : {zip_path} ({size_mb:.1f} MB)")
    print("=" * 68)


def choose_output_directory_interactive() -> Path:
    """Laat de gebruiker interactief een opslaglocatie kiezen (via pad of Windows Verkenner)."""
    default_dir = Path.cwd() / "exports"
    print("\nWaar wil je het Miro-bord en het ZIP-bestand opslaan?")
    print(f"  - Druk op [Enter] om een map te kiezen via Windows Verkenner")
    print(f"  - Of plak hier direct een map-pad (bijv. C:\\Users\\robbe\\Downloads)")
    try:
        user_input = input("> ").strip().strip('"').strip("'")
    except EOFError:
        user_input = ""

    if user_input:
        return Path(user_input)

    # Open Windows Verkenner map-keuzevenster via tkinter
    try:
        import tkinter as tk
        from tkinter import filedialog

        print("Map-keuzevenster openen...")
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="Kies waar het Miro-bord en het ZIP-bestand opgeslagen moeten worden",
            initialdir=str(Path.home()),
        )
        root.destroy()
        if selected:
            chosen = Path(selected)
            print(f"Gekozen opslaglocatie: {chosen}\n")
            return chosen
    except Exception:
        pass

    print(f"Standaardmap wordt gebruikt: {default_dir}\n")
    return default_dir


def main():
    parser = argparse.ArgumentParser(
        description="Download een publiek Miro bord volledig offline inclusief interactieve HTML viewer en ZIP-bestand."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="De URL van het publieke Miro bord (bijv. https://miro.com/app/board/uXjVEakmNhM=/)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="Map waarin de export en het ZIP-bestand worden opgeslagen (standaard: ./exports)",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Maak enkel de map aan en sla het maken van een .zip bestand over.",
    )
    args = parser.parse_args()

    url = args.url
    interactive_mode = not bool(url)
    if not url:
        print("=" * 68)
        print("  MIRO BORD OFFLINE DOWNLOADER & HTML VIEWER GENERATOR")
        print("=" * 68)
        try:
            url = input("Plak hier de Miro bord URL en druk op Enter:\n> ").strip()
        except EOFError:
            url = ""

    if not url:
        print("Geen URL opgegeven. Afgesloten.")
        sys.exit(1)

    output_dir = args.output_dir
    if output_dir is None and interactive_mode:
        output_dir = choose_output_directory_interactive()

    try:
        asyncio.run(run_export(url, base_output_dir=output_dir, create_zip=not args.no_zip))
    except KeyboardInterrupt:
        print("\nDownload geannuleerd door gebruiker.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FOUT] Er is een fout opgetreden: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
