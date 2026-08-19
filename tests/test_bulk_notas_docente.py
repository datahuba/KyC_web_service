import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bson import ObjectId
from models.enrollment import Enrollment, ModuloEstado
from models.user import User
from models.enums import UserRole
from services.enrollment_service import subir_notas_borrador_bulk
from schemas.enrollment import BulkNotaDocenteItem, BulkNotasDocenteRequest


@pytest.mark.asyncio
async def test_subir_notas_borrador_bulk_exito():
    eid1 = ObjectId()
    eid2 = ObjectId()

    # Mock de enrollments
    mock_enrollment1 = MagicMock()
    mock_enrollment1.id = eid1
    mock_enrollment1.modulos = [
        ModuloEstado(modulo_index=1, nombre="M1", estado="Cursando", costo=500.0),
        ModuloEstado(modulo_index=2, nombre="M2", estado="Cursando", costo=500.0)
    ]
    mock_enrollment1.save = AsyncMock()

    mock_enrollment2 = MagicMock()
    mock_enrollment2.id = eid2
    mock_enrollment2.modulos = [
        ModuloEstado(modulo_index=1, nombre="M1", estado="Cursando", costo=500.0)
    ]
    mock_enrollment2.save = AsyncMock()

    items = [
        BulkNotaDocenteItem(enrollment_id=str(eid1), modulo_index=0, nota=85.5),
        BulkNotaDocenteItem(enrollment_id=str(eid2), modulo_index=0, nota=92.0),
        BulkNotaDocenteItem(enrollment_id=str(ObjectId()), modulo_index=0, nota=70.0), # no existe
    ]

    with patch.object(Enrollment, "find") as mock_find:
        mock_find_ret = MagicMock()
        mock_find_ret.to_list = AsyncMock(return_value=[mock_enrollment1, mock_enrollment2])
        mock_find.return_value = mock_find_ret

        exitosos, fallidos, resultados = await subir_notas_borrador_bulk(items)

        assert exitosos == 2
        assert fallidos == 1
        assert len(resultados) == 3

        # Verificar que se setearon las notas y estados
        assert mock_enrollment1.modulos[0].nota_borrador == 85.5
        assert mock_enrollment1.modulos[0].estado_validacion_nota == "pendiente_validacion"
        assert mock_enrollment2.modulos[0].nota_borrador == 92.0
        assert mock_enrollment2.modulos[0].estado_validacion_nota == "pendiente_validacion"
        
        mock_enrollment1.save.assert_awaited_once()
        mock_enrollment2.save.assert_awaited_once()
