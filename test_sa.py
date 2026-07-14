import asyncio
import httpx

async def test_superadmin():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000/api/v1") as client:
        # We can bypass auth if DEVELOPMENT_MODE=True in backend, 
        # let's try to just hit GET /auth/me to see who we are
        res = await client.get("/auth/me")
        print("Auth me:", res.status_code, res.text)
        
        # Now try to create a course
        payload = {
            "codigo": "TEST-100",
            "nombre_programa": "Test Superadmin",
            "tipo_curso": "curso",
            "modalidad": "virtual",
            "costo_total_interno": 1000,
            "matricula_interno": 100,
            "cantidad_cuotas": 1,
            "modulos": [{"nombre": "Mod 1", "costo": 1000}]
        }
        res2 = await client.post("/courses/", json=payload)
        print("Create course:", res2.status_code, res2.text)

asyncio.run(test_superadmin())
