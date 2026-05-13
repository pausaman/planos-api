from fastapi import FastAPI, UploadFile, File
from typing import List
from openai import OpenAI
import fitz
import base64
import os
import json

app = FastAPI()

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
async def extract_batch(files: List[UploadFile] = File(...)):
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