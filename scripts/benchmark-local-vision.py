"""Compare installed vision models on small, inspectable synthetic fixtures."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from media_catalog.inference import LocalAnalyzer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    font = ImageFont.truetype('C:/Windows/Fonts/msjh.ttc', 32)
    fixtures = []
    for index in range(3):
        image = Image.new('RGB', (640, 360), 'white')
        draw = ImageDraw.Draw(image)
        if index == 0:
            draw.text((25, 20), '影片清冊 2026', fill='black', font=font)
            for x in (100, 270, 440):
                draw.ellipse((x, 130, x + 90, 220), fill='red')
            truth = '白底、三個紅色圓形、文字「影片清冊 2026」'
        elif index == 1:
            draw.text((25, 20), 'SALE 50%', fill='black', font=font)
            draw.rectangle((70, 130, 190, 260), fill='blue')
            draw.polygon([(320, 260), (440, 100), (560, 260)], fill='green')
            truth = '白底、一個藍色矩形、一個綠色三角形、SALE 50%'
        else:
            draw.text((25, 20), '會議室 A / 週報', fill='black', font=font)
            draw.rectangle((120, 120, 520, 270), fill='brown')
            for x in (180, 390):
                draw.ellipse((x, 75, x + 45, 120), fill='black')
            truth = '示意圖、棕色矩形桌面、兩個黑色圓形、文字「會議室 A / 週報」'
        path = args.output / f'frame-{index}.png'
        image.save(path)
        fixtures.append((path, truth))

    rows = []
    for model in ('Qwen3-vl:8b-instruct', 'qwen3.5:9b'):
        # Release the previous benchmark model before testing the next one.
        if rows:
            subprocess.run(['ollama', 'stop', rows[-1]['model']], capture_output=True)

        def runner(command, **kwargs):
            if model == 'qwen3.5:9b':
                command = [*command[:3], '--think=false', *command[3:]]
            return subprocess.run(command, **kwargs)

        analyzer = LocalAnalyzer(model=model, runner=runner, timeout=180)
        for path, truth in fixtures:
            start = time.monotonic()
            row = {'model': model, 'fixture': path.name, 'truth': truth,
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            try:
                row['analysis'] = asdict(analyzer.analyze_frames([path]))
                row['schema_ok'] = True
            except Exception as error:
                row['schema_ok'] = False
                row['error'] = str(error)
            row['seconds'] = round(time.monotonic() - start, 2)
            rows.append(row)
            (args.output / 'results.json').write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
