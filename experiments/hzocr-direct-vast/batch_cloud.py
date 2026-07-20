"""Cloud OCR worker for 杭州方言词典/音档小册子 pages.

Same dual-engine output schema as the local batch (batch_hz.py on thursday-win):
per page NNN → out_dir/<stem>.vl16.json (entry blocks with bbox)
           + out_dir/<stem>.ppocr.json (line items with bbox).
--reverse walks pages from the tail so a concurrently running local batch
(walking forward) and this worker meet in the middle with minimal overlap.
"""
import glob
import json
import os
import sys
import time
import traceback

pages_dir, out_dir = sys.argv[1], sys.argv[2]
reverse = "--reverse" in sys.argv[3:]
os.makedirs(out_dir, exist_ok=True)
log_path = os.path.join(out_dir, "progress.log")


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def vl_blocks(result):
    blocks = []
    for r in result:
        d = r.json["res"]
        for blk in d.get("parsing_res_list", []):
            bb = blk.get("block_bbox") or blk.get("bbox")
            blocks.append({
                "bbox": [float(v) for v in bb],
                "label": blk.get("block_label") or blk.get("label", ""),
                "content": blk.get("block_content") or blk.get("content", ""),
            })
    return blocks


def main():
    pages = sorted(glob.glob(os.path.join(pages_dir, "*.png")), reverse=reverse)
    log(f"START total={len(pages)} reverse={reverse}")

    from paddleocr import PaddleOCRVL, PaddleOCR
    vl = PaddleOCRVL(vl_rec_model_name="PaddleOCR-VL-1.6-0.9B")
    pp = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                   use_textline_orientation=False, lang="ch")

    for img in pages:
        stem = os.path.splitext(os.path.basename(img))[0]
        vl_out = os.path.join(out_dir, stem + ".vl16.json")
        pp_out = os.path.join(out_dir, stem + ".ppocr.json")
        if os.path.exists(vl_out) and os.path.exists(pp_out):
            continue
        t0 = time.time()
        try:
            if not os.path.exists(vl_out):
                blocks = vl_blocks(vl.predict(img))
                with open(vl_out, "w", encoding="utf-8") as f:
                    json.dump(blocks, f, ensure_ascii=False)
            if not os.path.exists(pp_out):
                d = pp.predict(img)[0]
                items = []
                for t, poly in zip(d["rec_texts"], d["rec_polys"]):
                    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
                    items.append({"text": t,
                                  "x0": float(min(xs)), "x1": float(max(xs)),
                                  "y0": float(min(ys)), "y1": float(max(ys))})
                with open(pp_out, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False)
            log(f"OK {stem} {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"FAIL {stem} {e!r}")
            with open(os.path.join(out_dir, stem + ".err"), "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())

    log("DONE")


if __name__ == "__main__":
    main()
