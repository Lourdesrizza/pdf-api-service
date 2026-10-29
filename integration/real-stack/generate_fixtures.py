from pathlib import Path
import argparse
import json
import hashlib


def make_pdf(marker: str) -> bytes:
    nl = b"\n"
    stream = b"BT\n/F1 18 Tf\n72 720 Td\n(" + marker.encode("ascii") + b") Tj\nET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(str(index).encode("ascii") + b" 0 obj\n" + obj + b"\nendobj\n")
    xref_offset = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n")
    output.extend(str(xref_offset).encode("ascii") + b"\n%%EOF\n")
    return bytes(output)


def main():
    parser = argparse.ArgumentParser(description="Generate tiny, synthetic one-page integration PDFs. Not official load-test data.")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("run"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "proof.pdf": "ISOLATED PDF API EXTRACTION PROOF",
        "concurrency.pdf": "CONCURRENT API DOCUMENT",
    }
    results = {}
    for filename, marker in fixtures.items():
        payload = make_pdf(marker)
        path = args.output / filename
        path.write_bytes(payload)
        results[filename] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "marker": marker}
    print(json.dumps({"fixture_type": "synthetic integration-only PDFs; not official dataset", "fixtures": results}, indent=2))


if __name__ == "__main__":
    main()
