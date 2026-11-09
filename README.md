<div align="center">
  <h1>Pinterest Mass Downloader</h1>
  <p><strong>Bulk-download Pinterest pictures, videos and GIFs, keep only the ones that look like the picture you love, and use them from your phone.</strong></p>

  <p>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square" alt="License: MIT" /></a>
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg?style=flat-square" alt="Platform" />
  </p>
</div>

<p align="center">
  <a href="https://github.com/IamOumarIbrahim/pinterest-mass-downloader-gui/releases/latest/download/pinterest_downloader.exe"><img alt="Download for Windows" src="https://img.shields.io/badge/Download-Windows%20.exe-e60023?style=for-the-badge&logo=windows&logoColor=white" /></a>
</p>

<p align="center">
  <a href="assets/demo.mp4"><img src="assets/demo.gif" alt="One-minute walkthrough: search, match a picture, download, share to phone" width="100%" /></a>
  <br />
  <sub>One-minute walkthrough. <a href="assets/demo.mp4">Watch it in full quality (MP4)</a>.</sub>
</p>

## Quickstart

```bash
git clone https://github.com/IamOumarIbrahim/pinterest-mass-downloader-gui.git
cd pinterest-mass-downloader-gui
pip install -r requirements.txt
python pinterest_downloader.py
```

Type something, press **Enter**. That's it. Everything else is optional and the app remembers your choices.

## How it works

| | Step | What you do |
|:-:|:--|:--|
| **1** | **Search** | Type a keyword (`fortnite llama`) or paste a board / pin link. Recent searches are one click away. |
| **2** | **How many** | Drag the Pictures, Videos and GIFs sliders. Set a slider to 0 to skip that type. |
| **3** | **Match a picture** *(optional)* | Drop a picture on the window, click to browse, or press **Ctrl+V**. Tick **Looks similar**, **Similar colors**, or both. |
| **4** | **Download** | Matches stream into the gallery with their match score. Click a tile to open it. |
| **5** | **Phone** *(optional)* | Scan the QR code and browse or share everything from bed. |

Use **+ Queue** to line up several searches and run them in one go. Each search gets its own folder.

## Match a picture

<p align="center"><img src="assets/app.png" alt="Matching against a reference picture: palette, tolerance and results" width="100%" /></p>

Pick a reference picture and the app checks every candidate against it before downloading. Only the winners are saved, best match first.

**Looks similar** compares composition, shapes and edges. **How close?** sets how picky it is: *Loosely related* keeps the best ~60% of what the search finds, *Nearly identical* keeps the top ~8%.

**Similar colors** turns the picture into a palette (the color bar) and checks that each download is made of those colors. **Color tolerance** decides how much the *amounts* may differ:

| Tolerance | Meaning | A grey / black / red reference matches... |
|:--|:--|:--|
| **0–15** Strict | same colors in almost the same amounts | mostly grey, some black, a little red |
| **15–40** Close | amounts may shift a little | a bit more black, a bit less grey |
| **40–70** Relaxed | amounts can change a lot | half red, half grey |
| **70–100** Loose | same colors in any amount | any mix of grey, black and red |

Each swatch shows its allowed range live, for example `37% → 2%–73%`. Two sensible limits always apply. Every main color must appear at least a little. And at the strict end, colors that aren't in the palette (a different background, say) can only take up a small share.

**Pick your own colors.** Click **+ Pick a color** to add any color, or click a swatch to remove it. This works without a reference picture too: pick red and black and you'll only get red-and-black pins.

> [!TIP]
> Nothing matched? The keyword picks the subject and the picture narrows it down, so be specific (`fortnite llama`, not `fortnite`). You can also raise the tolerance or lower **How close?**.

## Use your downloads on your phone

<p align="center"><img src="assets/phone.png" alt="Phone gallery: albums and a grid of downloads" width="70%" /></p>

Leave the PC on and go lie down. Click **Phone** in the app, scan the QR code with your phone's camera, and your download folder opens as a gallery in the phone's browser. Nothing is copied to the phone: pictures are streamed from your D: drive (or whichever folder you pick) only when you look at them.

- **Share to Instagram, WhatsApp, TikTok...** Tap a picture, tap **Share**, pick the app. Or use **Select** to share several at once, for example as a carousel.
- **Albums** match your folders, with the newest downloads first. Swipe left and right in the viewer. Videos play inline.
- **Add it to your home screen** (browser menu → *Add to Home screen*) so it opens like an app.
- Tick **Turn on automatically when the app opens** so the gallery is always available.

> [!NOTE]
> **Why "Share" and not Instagram's own attach button?** Instagram's picker only shows the phone's photo library, so no app can put a PC folder in there without saving the files on the phone. Going the other way works: open the gallery, tap **Share**, choose Instagram. The picture goes straight into your post, story or DM and never lands in your camera roll.

**One-tap Share buttons** need a secure (HTTPS) page. On plain Wi-Fi links you can always **long-press** a picture to share or copy it. For the buttons, tap *switch to secure mode* in the gallery and accept the one-time "certificate is self-made" warning (*Advanced → Proceed*).

**Privacy:** the gallery only works on your home network and only with the secret key built into the QR code. Other devices on the Wi-Fi get a locked page. The first time, Windows may ask about the firewall: allow **Private networks**.

You can also start it without the app:

```bash
python pinterest_downloader.py --phone "D:\Pinterest"
```

## Command line

Every app feature is also available from a terminal:

```bash
python pinterest_downloader.py --keyword "fortnite llama" --limit 30 --out "D:\Pinterest"
python pinterest_downloader.py --board "https://pinterest.com/user/board" --videos 10 --gifs 10
python pinterest_downloader.py -k "fortnite llama" -r llama.jpg --similar --colors --tolerance 60
```

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--keyword`, `-k` | Search term | |
| `--board`, `-b` | Board or pin URL (`pin.it` short links work) | |
| `--phone FOLDER` | Share a folder with your phone (prints a QR code) | |
| `--limit`, `-n` | Number of pictures | 50 |
| `--videos` / `--gifs` | Number of videos / GIFs | 0 |
| `--out`, `-o` | Output folder | `./downloads` |
| `--threads` | Parallel downloads (1-32) | 8 |
| `--reference`, `-r` | Reference picture | |
| `--similar` / `--colors` | Match its look / its colors | look, if `-r` is given |
| `--tolerance` | Color tolerance, 0 (same amounts) to 100 (any amounts) | 50 |
| `--closeness` | Look-alike strictness, 0 to 100 | 50 |

## Good to know

- **You only get what you asked for.** Every file is checked after downloading: pictures are real still images, GIFs are animated, and videos are real videos. A pin that turns out to be the wrong type is deleted and replaced with the next candidate.
- **No duplicates.** Files are named by pin ID, so running the same search again skips what you already have. Interrupted downloads never leave half-written files behind.
- **Settings** (folder, sliders, reference, phone key) are stored in `%APPDATA%\PinterestMassDownloader`.

<details>
<summary><b>Project layout</b></summary>

```
pinterest_downloader.py   entry point (app, or CLI when given arguments)
pinmass/
  gui.py                  desktop app (customtkinter)
  worker.py               search, match, download pipeline
  scraper.py              Pinterest search / board scraping
  media.py                downloads + file-type verification
  matching.py             look-alike and color matching (numpy)
  phone.py, phone_page.html   phone gallery server and web app
  cli.py, settings.py
tests/unit/               pytest suite
tools/demo/               scripts that record and edit the demo video above
```

Run the tests with `python -m pytest tests`. To re-record the demo, run `python tools/demo/record_demo.py <reference.jpg> <workdir>` and then `python tools/demo/compose_video.py <workdir> assets/demo.mp4 assets/demo.gif`.
</details>

## Help the project

Did this help you? Please give it a **star**, so more people can find it. Bugs and ideas are welcome in [Issues](https://github.com/IamOumarIbrahim/pinterest-mass-downloader-gui/issues).

## License

MIT License.
