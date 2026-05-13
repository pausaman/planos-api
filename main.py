from fastapi import FastAPI, UploadFile, File
from openai import OpenAI
import fitz
import base64
import os

app = FastAPI()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):

    pdf_bytes = await file.read()

    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

    page = pdf[0]

    pix = page.get_pixmap(dpi=200)

    image_bytes = pix.tobytes("png")

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-5",
        response_format={
            "type": "json_object"
        },
        messages=[
            {
                "role": "system",
                "content": """
                Extrae información estructurada de planos de acero.
                Responde SOLO JSON válido.
                """
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """
                        Extrae:
                        - mark
                        - quantity
                        - profile
                        - grade
                        - length_mm
                        - holes_mm
                        - unit_weight_kg
                        - total_weight_kg
                        """
                    },
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

    return response.choices[0].message.content