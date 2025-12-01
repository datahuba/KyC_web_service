"""
Utilidades Base y Tipos Personalizados
======================================

Este módulo contiene las clases base y utilidades compartidas por todos los modelos.

Componentes:
-----------
1. PyObjectId: Tipo personalizado para manejar ObjectId de MongoDB con Pydantic
2. MongoBaseModel: Clase base para todos los documentos de MongoDB

¿Por qué estos componentes?
---------------------------
- PyObjectId: Pydantic no soporta nativamente ObjectId de MongoDB, necesitamos
  un tipo personalizado que valide y serialice correctamente los IDs.
  
- MongoBaseModel: Todos los documentos en MongoDB necesitan:
  * Un campo _id (manejado como 'id' en Python)
  * Timestamps de creación y actualización
  * Configuración común de serialización
  
  Al heredar de esta clase, todos los modelos obtienen estas características
  automáticamente, evitando duplicación de código.
"""

from datetime import datetime
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    """
    Tipo personalizado para ObjectId de MongoDB compatible con Pydantic
    
    ¿Por qué necesitamos esto?
    -------------------------
    MongoDB usa ObjectId como identificador único, pero Pydantic (usado para
    validación) no lo reconoce nativamente. Esta clase actúa como puente:
    
    1. Valida que las cadenas sean ObjectIds válidos
    2. Convierte automáticamente entre string y ObjectId
    3. Permite que Pydantic genere schemas JSON correctos
    
    Ejemplo de uso:
    --------------
    estudiante_id: PyObjectId = Field(...)
    # Acepta: "507f1f77bcf86cd799439011" (string)
    # Convierte a: ObjectId("507f1f77bcf86cd799439011")
    """
    
    @classmethod
    def __get_validators__(cls):
        """Registra el validador personalizado con Pydantic"""
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        """
        Valida que el valor sea un ObjectId válido
        
        Args:
            v: Valor a validar (puede ser string u ObjectId)
            
        Returns:
            ObjectId validado
            
        Raises:
            ValueError: Si el valor no es un ObjectId válido
        """
        if not ObjectId.is_valid(v):
            raise ValueError("ObjectId inválido")
        return ObjectId(v)
    
    @classmethod
    def __modify_schema__(cls, field_schema):
        """
        Modifica el schema JSON para documentación de API
        
        Le dice a Pydantic que en el schema JSON, este campo
        debe aparecer como tipo 'string' en lugar de un tipo complejo
        """
        field_schema.update(type="string")


class MongoBaseModel(BaseModel):
    """
    Modelo base para todos los documentos de MongoDB
    
    ¿Por qué heredar de esta clase?
    -------------------------------
    Todos los documentos en MongoDB comparten características comunes:
    
    1. **Campo _id**: MongoDB requiere un identificador único
       - En MongoDB se llama '_id'
       - En Python lo usamos como 'id' (más pythónico)
       - Se genera automáticamente si no se proporciona
    
    2. **Timestamps automáticos**:
       - created_at: Cuándo se creó el documento (nunca cambia)
       - updated_at: Última modificación (se actualiza manualmente)
       - Útil para auditoría y debugging
    
    3. **Configuración de serialización**:
       - Convierte ObjectId a string para JSON
       - Convierte datetime a ISO 8601 para JSON
       - Permite usar tanto 'id' como '_id' en el código
    
    Ejemplo de herencia:
    -------------------
    class Student(MongoBaseModel):
        nombre: str
        email: str
    
    # Automáticamente tendrá: id, created_at, updated_at
    """
    
    id: PyObjectId = Field(
        default_factory=PyObjectId,
        alias="_id",
        description="Identificador único del documento en MongoDB"
    )
    
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Fecha y hora de creación del documento"
    )
    
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Fecha y hora de última actualización"
    )
    
    class Config:
        """
        Configuración de Pydantic para este modelo
        
        - allow_population_by_field_name: Permite usar tanto 'id' como '_id'
        - arbitrary_types_allowed: Permite usar ObjectId (tipo no estándar)
        - json_encoders: Define cómo convertir tipos especiales a JSON
        """
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str,  # ObjectId → string
            datetime: lambda v: v.isoformat()  # datetime → ISO 8601
        }
