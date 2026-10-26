"""Optional Pillow helper: scale native renders for 180mm/96dpi screen proof.
Not a replacement renderer and not a physical printer calibration.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paperfigure import storage


def main():
    from PIL import Image
    parser=argparse.ArgumentParser();parser.add_argument('runs');args=parser.parse_args()
    runs=storage.read_json(args.runs);images=[];records=[]
    for run in runs:
        task=Path(run['task']);src=task/'figure-v2.png'
        image=Image.open(src).convert('RGB');width=round(180/25.4*96)
        proof=image.resize((width,round(image.height*width/image.width)),Image.Resampling.LANCZOS)
        out=task/'print-proof-180mm-96dpi.png';proof.save(out,dpi=(96,96));images.append(proof)
        records.append({'source':str(src),'source_sha256':storage.digest(src),'proof':str(out),'width_mm':180,'screen_dpi_assumption':96,'not_physical_calibration':True})
    sheet=Image.new('RGB',(720,sum(im.height for im in images)+40*(len(images)+1)), 'white')
    y=40
    for image in images:sheet.paste(image,(20,y));y+=image.height+40
    base=Path(args.runs).parent;sheet.save(base/'overview.png');storage.write_json(base/'print-proof.json',records)
    print(base/'overview.png')


if __name__=='__main__':main()
