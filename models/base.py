"""
Utilidades Base y Tipos Personalizados
======================================

Este módulo contiene las clases base y utilidades compartidas por todos los modelos.
Ahora utiliza **Beanie ODM** para integración directa con MongoDB.
"""

from datetime import datetime
from typing import Optional
from pydantic import Field
from beanie import Document, PydanticObjectId
from bson import ObjectId

# Mantenemos PyObjectId por compatibilidad con schemas existentes,
# pero ahora es un alias de PydanticObjectId de Beanie
PyObjectId = PydanticObjectId

class MongoBaseModel(Document):
    """
    Modelo base para todos los documentos de MongoDB usando Beanie
    
    Características:
    ---------------
    1. **Herencia de Beanie**: Provee métodos CRUD (find, create, etc.)
    2. **Timestamps automáticos**: created_at y updated_at
    3. **ID automático**: Beanie maneja el _id automáticamente
    
    Uso:
    ----
    class Student(MongoBaseModel):
        nombre: str
        
        class Settings:
            name = "students"  # Nombre de la colección
    """
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    async def save(self, *args, **kwargs):
        """Sobrescribe save para actualizar updated_at"""
        self.updated_at = datetime.utcnow()
        return await super().save(*args, **kwargs)
    
    class Settings:
        """
        Configuración por defecto de Beanie
        
        use_state_management: Permite trackear cambios en el modelo
        validate_on_save: Valida los datos antes de guardar
        """
        use_state_management = True
        validate_on_save = True
