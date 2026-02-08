from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

import camelot
import pdfplumber

PDF_PATH = Path("./tools/source/ТССЦ-1_Часть_1._Материалы_для_общестроительных_работ.pdf")
OUT_DIR = Path("./out")

CODE_RE = re.compile(r"^\d{3}-\d{4}\b")
PRICE_RE = re.compile(r"^\d+[\.,]\d+$|^\d+$")
UNIT_RE = re.compile(r"^[а-яА-Яa-zA-Z\.²³/]+$")

TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 3,
    "min_words_vertical": 1,
    "min_words_horizontal": 1,
}

HEADER_PREFIXES = (
	"ТССЦ-",
	"Шифр",
	"Строительные материалы",
	"ресурса",
	"1 2 3 4 5",
)


@dataclass
class Item:
	code: str
	name: str
	unit: str
	price_release: Optional[str]
	price_estimate: Optional[str]
	section: Optional[str]
	subsection: Optional[str]
	group: Optional[str]
	spec: Optional[str]


def is_header_line(line: str) -> bool:
	return line.startswith(HEADER_PREFIXES)


def normalize_price(tokens: list[str]) -> Optional[str]:
	if not tokens:
		return None

	if len(tokens) == 1 and PRICE_RE.match(tokens[0]):
		return tokens[0]

	if len(tokens) == 2 and PRICE_RE.match(tokens[1]) and tokens[0].isdigit():
		return f"{tokens[0]}{tokens[1]}"

	return None


def parse_item_line(line: str) -> Optional[tuple[str, str, str, Optional[str], Optional[str]]]:
	tokens = line.split()
	if not tokens or not CODE_RE.match(tokens[0]):
		return None

	code = tokens[0]
	if len(tokens) < 4:
		return None

	price_release = None
	price_estimate = None

	for split in (2, 3, 4):
		tail = tokens[-split:]
		if split == 2:
			p1 = normalize_price(tail[:1])
			p2 = normalize_price(tail[1:2])
		elif split == 3:
			p1 = normalize_price(tail[:2])
			p2 = normalize_price(tail[2:3])
			if not (p1 and p2):
				p1 = normalize_price(tail[:1])
				p2 = normalize_price(tail[1:3])
		else:
			p1 = normalize_price(tail[:2])
			p2 = normalize_price(tail[2:4])

		if p1 and p2:
			price_release, price_estimate = p1, p2
			unit = tokens[-split - 1]
			name_tokens = tokens[1:-split - 1]
			break
	else:
		if PRICE_RE.match(tokens[-1]):
			price_estimate = tokens[-1]
			unit = tokens[-2]
			name_tokens = tokens[1:-2]
		else:
			unit = tokens[-1]
			name_tokens = tokens[1:-1]

	if name_tokens and name_tokens[-1].isdigit() and UNIT_RE.match(unit):
		unit = f"{name_tokens.pop(-1)} {unit}"

	if not UNIT_RE.match(unit.replace(" ", "")):
		if name_tokens:
			unit = name_tokens.pop(-1)

	name = " ".join(name_tokens).strip()
	return code, name, unit, price_release, price_estimate


def clean_cell(value: Optional[str]) -> str:
	if value is None:
		return ""
	return " ".join(value.replace("\n", " ").split()).strip()


def normalize_price_cell(value: str) -> Optional[str]:
	tokens = value.split()
	return normalize_price(tokens)


def is_header_row(cells: list[str]) -> bool:
	if not cells:
		return True
	first = cells[0]
	if not first:
		first = " ".join(cells[:2]).strip()
	return first.startswith(HEADER_PREFIXES)


def parse_item_row(cells: list[str]) -> Optional[tuple[str, str, str, Optional[str], Optional[str]]]:
	if len(cells) < 5:
		return None

	code = cells[0]
	if not CODE_RE.match(code):
		return None

	name = cells[1]
	unit = cells[2]
	price_release = normalize_price_cell(cells[3])
	price_estimate = normalize_price_cell(cells[4])

	return code, name, unit, price_release, price_estimate


def extract_context_from_cells(cells: list[str]) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
	section = None
	subsection = None
	group = None
	spec = None

	for cell in cells:
		if cell.startswith("Раздел"):
			section = cell
		elif cell.startswith("Подраздел:"):
			subsection = cell.replace("Подраздел:", "").strip()
		elif cell.startswith("Группа:"):
			group = cell.replace("Группа:", "").strip()
		elif cell.endswith(":"):
			spec = cell.rstrip(":").strip()

	return section, subsection, group, spec


def iter_lines(
	pdf_path: Path,
	page_start: int = 0,
	page_end: Optional[int] = None,
	method: str = "simple",
	progress_every: int = 25,
) -> Iterable[str]:
	with pdfplumber.open(pdf_path) as pdf:
		total = len(pdf.pages)
		end = page_end if page_end is not None else total
		end = min(end, total)

		for idx in range(page_start, end):
			if progress_every > 0 and (idx - page_start) % progress_every == 0:
				print(f"page {idx + 1}/{end}")

			page = pdf.pages[idx]
			try:
				if method == "layout":
					text = page.extract_text() or ""
				else:
					text = page.extract_text_simple() or ""
			except Exception as exc:
				print(f"warn: page {idx + 1} skipped: {exc}")
				continue

			for line in text.splitlines():
				yield line.strip()


def parse_pdf(
	pdf_path: Path,
	page_start: int = 0,
	page_end: Optional[int] = None,
	method: str = "simple",
	progress_every: int = 25,
) -> list[Item]:
	items: list[Item] = []
	section: Optional[str] = None
	subsection: Optional[str] = None
	group: Optional[str] = None
	spec: Optional[str] = None
	last_item: Optional[Item] = None

	if method == "camelot":
		total = page_end if page_end is not None else None
		if total is None:
			with pdfplumber.open(pdf_path) as pdf:
				total = len(pdf.pages)
		end = min(page_end, total) if page_end is not None else total

		for page_idx in range(page_start, end):
			if progress_every > 0 and (page_idx - page_start) % progress_every == 0:
				print(f"page {page_idx + 1}/{end}")

			tables = camelot.read_pdf(
				str(pdf_path),
				pages=str(page_idx + 1),
				flavor="stream",
			)

			for table in tables:
				df = table.df
				for row in df.itertuples(index=False):
					cells = [clean_cell(c) for c in row]
					if not any(cells):
						continue

					ctx_section, ctx_subsection, ctx_group, ctx_spec = extract_context_from_cells(cells)
					if ctx_section:
						section = ctx_section
						spec = None
					if ctx_subsection:
						subsection = ctx_subsection
						spec = None
					if ctx_group:
						group = ctx_group
						spec = None
					if ctx_spec:
						spec = ctx_spec
						last_item = None
						continue

					if is_header_row(cells):
						continue

					parsed = parse_item_row(cells)
					if parsed:
						code, name, unit, price_release, price_estimate = parsed
						item = Item(
							code=code,
							name=name,
							unit=unit,
							price_release=price_release,
							price_estimate=price_estimate,
							section=section,
							subsection=subsection,
							group=group,
							spec=spec,
						)
						items.append(item)
						last_item = item
						continue

					if cells and cells[0] == "" and len(cells) > 1 and cells[1]:
						if cells[1].endswith(":"):
							spec = cells[1].rstrip(":").strip()
							last_item = None
						elif last_item is not None:
							last_item.name = f"{last_item.name} {cells[1]}".strip()

		return items

	if method == "table":
		with pdfplumber.open(pdf_path) as pdf:
			total = len(pdf.pages)
			end = page_end if page_end is not None else total
			end = min(end, total)

			for idx in range(page_start, end):
				if progress_every > 0 and (idx - page_start) % progress_every == 0:
					print(f"page {idx + 1}/{end}")

				page = pdf.pages[idx]
				text = page.extract_text_simple() or ""
				for raw_line in text.splitlines():
					raw_line = raw_line.strip()
					if not raw_line:
						continue
					if is_header_line(raw_line):
						continue
					if raw_line.startswith("Раздел"):
						section = raw_line
						spec = None
						continue
					if raw_line.startswith("Подраздел:"):
						subsection = raw_line.replace("Подраздел:", "").strip()
						spec = None
						continue
					if raw_line.startswith("Группа:"):
						group = raw_line.replace("Группа:", "").strip()
						spec = None
						continue
					if raw_line.endswith(":"):
						spec = raw_line.rstrip(":").strip()
						last_item = None

				table = page.extract_table(TABLE_SETTINGS)
				if not table:
					continue

				for row in table:
					cells = [clean_cell(c) for c in row]
					if is_header_row(cells):
						continue

					parsed = parse_item_row(cells)
					if parsed:
						code, name, unit, price_release, price_estimate = parsed
						item = Item(
							code=code,
							name=name,
							unit=unit,
							price_release=price_release,
							price_estimate=price_estimate,
							section=section,
							subsection=subsection,
							group=group,
							spec=spec,
						)
						items.append(item)
						last_item = item
						continue

					if cells[0] == "" and cells[1]:
						if cells[1].endswith(":"):
							spec = cells[1].rstrip(":").strip()
							last_item = None
						elif last_item is not None:
							last_item.name = f"{last_item.name} {cells[1]}".strip()

		return items

	for raw_line in iter_lines(
		pdf_path,
		page_start=page_start,
		page_end=page_end,
		method=method,
		progress_every=progress_every,
	):
		if not raw_line:
			continue
		if is_header_line(raw_line):
			continue

		if raw_line.startswith("Раздел"):
			section = raw_line
			spec = None
			continue

		if raw_line.startswith("Подраздел:"):
			subsection = raw_line.replace("Подраздел:", "").strip()
			spec = None
			continue

		if raw_line.startswith("Группа:"):
			group = raw_line.replace("Группа:", "").strip()
			spec = None
			continue

		parsed = parse_item_line(raw_line)
		if parsed:
			code, name, unit, price_release, price_estimate = parsed
			item = Item(
				code=code,
				name=name,
				unit=unit,
				price_release=price_release,
				price_estimate=price_estimate,
				section=section,
				subsection=subsection,
				group=group,
				spec=spec,
			)
			items.append(item)
			last_item = item
			continue

		if raw_line.endswith(":"):
			spec = raw_line.rstrip(":").strip()
			last_item = None
			continue

		if last_item is not None:
			last_item.name = f"{last_item.name} {raw_line}".strip()
			continue

		spec = raw_line

	return items


def write_outputs(items: list[Item], out_dir: Path, stem: str) -> None:
	out_dir.mkdir(parents=True, exist_ok=True)

	jsonl_path = out_dir / f"items_{stem}.jsonl"
	with jsonl_path.open("w", encoding="utf-8") as f:
		for item in items:
			data = asdict(item)
			f.write(json.dumps(data, ensure_ascii=False) + "\n")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Parse TSSC PDF into structured items.")
	parser.add_argument(
		"--pdf",
		action="append",
		default=[],
		help="Path to PDF file (can be used multiple times)",
	)
	parser.add_argument(
		"--pdf-glob",
		default="./tools/source/*.pdf",
		help="Glob for PDF files when --pdf not provided",
	)
	parser.add_argument("--page-start", type=int, default=0, help="Start page index (0-based)")
	parser.add_argument("--page-end", type=int, default=None, help="End page index (exclusive)")
	parser.add_argument(
		"--method",
		choices=["simple", "layout", "table", "camelot"],
		default="simple",
		help="Text extraction method",
	)
	parser.add_argument(
		"--progress-every",
		type=int,
		default=25,
		help="Print progress every N pages (0 disables)",
	)
	args = parser.parse_args()

	if args.pdf:
		pdfs = [Path(p) for p in args.pdf]
	else:
		glob_path = Path(args.pdf_glob)
		if glob_path.is_absolute():
			pdfs = list(glob_path.parent.glob(glob_path.name))
		else:
			pdfs = list(Path().glob(args.pdf_glob))

	if not pdfs:
		raise SystemExit("No PDF files found")

	for idx, pdf_path in enumerate(pdfs, start=1):
		if not pdf_path.exists():
			print(f"skip missing: {pdf_path}")
			continue

		print(f"file {idx}/{len(pdfs)}: {pdf_path.name}")
		parsed = parse_pdf(
			pdf_path,
			page_start=args.page_start,
			page_end=args.page_end,
			method=args.method,
			progress_every=args.progress_every,
		)
		write_outputs(parsed, OUT_DIR, pdf_path.stem)
		print(f"parsed items: {len(parsed)}")
		print(f"written to: {OUT_DIR}")
