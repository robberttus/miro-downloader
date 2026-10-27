# Miro Bord Offline Downloader

Een volledig zelfstandig Python-script (geïnspireerd door [`jolle/miro-export`](https://github.com/jolle/miro-export)) waarmee je **zonder AI-tussenkomst** elk publiek Miro-bord kunt downloaden naar een `.zip`-bestand én een uitgepakte map met een interactieve offline HTML-viewer (`board_viewer.html`).

## 🚀 Hoe te gebruiken

### Optie 1: Dubbelklikken (Windows)
1. Dubbelklik op **`start_downloader.bat`**.
2. Plak de URL van het publieke Miro-bord (bijv. `https://miro.com/app/board/uXjVEakmNhM=/`) en druk op **Enter**.
3. Het script downloadt automatisch alle kaders, post-its, teksten, voorvertoningen en originele hoge-resolutie bestanden (afbeeldingen & PDF's) en maakt zowel een map als een `.zip`-bestand aan in de map `exports/`.

### Optie 2: Via de terminal / PowerShell
```powershell
python miro_downloader.py "https://miro.com/app/board/uXjVEakmNhM=/"
```
Of met een eigen doelmap:
```powershell
python miro_downloader.py "https://miro.com/app/board/uXjVEakmNhM=/" --output-dir "C:\Pad\Naar\Doelmap"
```

## 📦 Wat zit er in de export en het `.zip`-bestand?
Wanneer je het `.zip`-bestand uitpakt (of de gegenereerde map in `exports/` opent), vind je exact dezelfde opbouw als je eerdere Miro-export:
- **`board_viewer.html`** — Dubbelklik hierop om het Miro-bord **100% offline** in je browser te bekijken:
  - Vloeiend pannen en in-/uitzoomen op het volledige canvas
  - Interactieve **Minimap** rechtsonder
  - **Zoekbalk** rechtsboven om direct op naam, bestandsnaam, kader of post-it te zoeken en ernaartoe te vliegen
  - **Lightbox-venster** wanneer je op een afbeelding of PDF klikt, met resolutie, bestandsgrootte en een knop **"Open Origineel Bestand"**
- **`images/`** — Alle originele hoge-resolutie afbeeldingen en PDF-documenten
- **`thumbnails/`** — Geoptimaliseerde preview-afbeeldingen voor vloeiende weergave op het canvas
- **`overzicht_studenten_en_bestanden.csv`** — Excel-overzicht (puntkomma-gescheiden) met alle bestanden, afmetingen en X/Y-coördinaten
- **`board_data.json` & `resource_map.json`** — Alle gestructureerde coördinaten en metadata van het bord
- **`README.md`** — Overzicht en statistieken van het gedownloade bord

## ⚙️ Vereisten (indien op een nieuwe pc geïnstalleerd)
Op deze computer zijn alle benodigdheden al geïnstalleerd. Moet je het ooit op een andere pc installeren, voer dan eenmalig uit:
```powershell
pip install -r requirements.txt
playwright install chromium
```
