from fastapi import FastAPI, UploadFile, File
from typing import List, Annotated
from openai import OpenAI
import fitz
import base64
import os
import json
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from copy import copy
from openpyxl import load_workbook
import io

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@app.get("/")
def root():
    return {"status": "ok"}


def pdf_to_base64_image(pdf_bytes: bytes) -> str:
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = pdf[0]
    pix = page.get_pixmap(dpi=250)
    image_bytes = pix.tobytes("png")
    return base64.b64encode(image_bytes).decode("utf-8")


def extract_from_pdf_image(base64_image: str, filename: str):
    prompt = f"""
Extrae información estructurada de este plano de acero tipo Tekla.

Archivo fuente: {filename}

Reglas:
- Responde SOLO JSON válido.
- No inventes datos.
- Si un dato no aparece, usa null.
- Extrae las posiciones horizontales de barrenaciones en milímetros.
- No cuentes los barrenos como resultado principal.
- No conviertas Ø 5/8" a milímetros; guárdalo como "5/8 in".
- La pestaña destino debe ser el perfil principal, por ejemplo "8C3014".
- Distingue entre el peso del material principal, clip y totales generales.
- Si existe clip L6, extrae sus datos por separado.
- Extrae Unit Weight Kg, Tot Weight Kg y Painting Area m2.

Devuelve exactamente esta estructura:

{{
  "source_file": "{filename}",
  "mark": null,
  "cantidad_piezas": null,
  "target_sheet": null,
  "titulo": null,
  "project_no": null,
  "proyecto": null,
  "fase": null,
  "fecha": null,
  "revision": null,
  "archivo_plano": null,
  "material_principal": {{
    "mark": null,
    "qty": null,
    "profile": null,
    "grade": null,
    "length_mm": null,
    "unit_weight_kg": null,
    "total_weight_kg": null
  }},
  "clip": {{
    "mark": null,
    "qty": null,
    "profile": null,
    "grade": null,
    "length_mm": null,
    "unit_weight_kg": null,
    "total_weight_kg": null
  }},
  "totales": {{
    "unit_weight_kg": null,
    "total_weight_kg": null,
    "painting_area_m2": null
  }},
  "barrenos": {{
    "diametro": null,
    "posiciones_mm": [],
    "separacion_vertical_mm": null,
    "offset_vertical_mm": null
  }},
  "soldadura": {{
    "tipo": null,
    "tamano": null
  }},
  "elevacion": null,
  "validation_status": "pending"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Eres un extractor especializado en planos estructurales Tekla. Devuelves exclusivamente JSON válido."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
    )

    content = response.choices[0].message.content
    return json.loads(content)


@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    base64_image = pdf_to_base64_image(pdf_bytes)
    result = extract_from_pdf_image(base64_image, file.filename)
    return result


@app.post("/extract-batch")
async def extract_batch(
    files: Annotated[List[UploadFile], File(description="Archivos PDF a procesar")]
):
    items = []

    for file in files:
        pdf_bytes = await file.read()
        base64_image = pdf_to_base64_image(pdf_bytes)
        result = extract_from_pdf_image(base64_image, file.filename)
        items.append(result)

    return {
        "items": items,
        "count": len(items)
    }


def copy_row_style(sheet, source_row: int, target_row: int):
    for col in range(1, sheet.max_column + 1):
        source_cell = sheet.cell(row=source_row, column=col)
        target_cell = sheet.cell(row=target_row, column=col)

        if source_cell.has_style:
            target_cell._style = copy(source_cell._style)

        if source_cell.number_format:
            target_cell.number_format = source_cell.number_format

        if source_cell.alignment:
            target_cell.alignment = copy(source_cell.alignment)

        if source_cell.border:
            target_cell.border = copy(source_cell.border)

        if source_cell.fill:
            target_cell.fill = copy(source_cell.fill)


def find_next_row(sheet):
    return sheet.max_row + 1


def get_holes(record):
    barrenos = record.get("barrenos") or {}
    return barrenos.get("posiciones_mm") or []


def write_record_to_sheet(sheet, record):
    new_row = find_next_row(sheet)
    template_row = new_row - 1

    if template_row >= 1:
        copy_row_style(sheet, template_row, new_row)

    material = record.get("material_principal") or {}
    totales = record.get("totales") or {}
    clip = record.get("clip") or {}
    soldadura = record.get("soldadura") or {}
    holes = get_holes(record)

    # Mapeo inicial de columnas.
    # Ajustaremos este mapa conforme al formato real del Excel.
    values = {
        "A": record.get("folio") or "",
        "B": f"*{record.get('mark')}" if record.get("mark") else "",
        "C": record.get("cantidad_piezas"),
        "D": material.get("profile") or record.get("target_sheet"),
        "E": material.get("length_mm"),

        # Posiciones de barrenos
        "F": holes[0] if len(holes) > 0 else None,
        "G": holes[1] if len(holes) > 1 else None,
        "H": holes[2] if len(holes) > 2 else None,
        "I": holes[3] if len(holes) > 3 else None,
        "J": holes[4] if len(holes) > 4 else None,
        "K": holes[5] if len(holes) > 5 else None,
        "L": holes[6] if len(holes) > 6 else None,
        "M": holes[7] if len(holes) > 7 else None,

        "N": "VER PLANO DE TALLER PARA HAB",
        "O": "CLIPS" if clip and clip.get("mark") else "",
        "P": soldadura.get("tamano"),
        "Q": "*",
        "R": material.get("unit_weight_kg"),
        "S": "S2"
    }

    for col, value in values.items():
        sheet[f"{col}{new_row}"] = value

    return new_row


@app.post("/generate-excel")
async def generate_excel(
    template: UploadFile = File(...),
    records_json: str = File(...)
):
    template_bytes = await template.read()
    records_payload = json.loads(records_json)

    if isinstance(records_payload, dict) and "items" in records_payload:
        records = records_payload["items"]
    elif isinstance(records_payload, list):
        records = records_payload
    else:
        records = [records_payload]

    keep_vba = template.filename.lower().endswith(".xlsm")

    workbook = load_workbook(
        filename=io.BytesIO(template_bytes),
        keep_vba=keep_vba
    )

    inserted = []

    for record in records:
        target_sheet = record.get("target_sheet")

        if not target_sheet:
            material = record.get("material_principal") or {}
            target_sheet = material.get("profile")

        if not target_sheet:
            continue

        if target_sheet not in workbook.sheetnames:
            continue

        sheet = workbook[target_sheet]
        row = write_record_to_sheet(sheet, record)

        inserted.append({
            "mark": record.get("mark"),
            "target_sheet": target_sheet,
            "row": row
        })

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    filename = "excel_generado.xlsm" if keep_vba else "excel_generado.xlsx"

    media_type = (
        "application/vnd.ms-excel.sheet.macroEnabled.12"
        if keep_vba
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Inserted-Rows": json.dumps(inserted)
    }

    return StreamingResponse(
        output,
        media_type=media_type,
        headers=headers
    )