from decimal import Decimal

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import obtener_encuentro,registrar_auditoria

router=APIRouter()

class DetalleAdicional(BaseModel):
    concepto:str=Field(max_length=200)
    cantidad:int=Field(default=1,gt=0)
    valor_unitario:Decimal=Field(ge=0)

class FacturaCreate(BaseModel):
    id_encuentro:int
    numero_factura:str=Field(max_length=50)
    concepto:str|None=None
    incluir_prescripciones_dispensadas:bool=True
    incluir_examenes_completados:bool=True
    detalles_adicionales:list[DetalleAdicional]=Field(default_factory=list)

@router.post("/facturas",tags=["Facturación"],status_code=201)
def crear_factura(data:FacturaCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Contable"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,data.id_encuentro,False)

        if not e:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado")

        if e["estado"]!="finalizado":
            raise HTTPException(status_code=409,detail="Solo se factura un encuentro finalizado")

        cur.execute("""
            INSERT INTO facturas(
                id_paciente,id_encuentro,numero_factura,
                concepto,total,creado_por
            )
            VALUES(%s,%s,%s,%s,0,%s)
            RETURNING *;
        """,(
            e["id_paciente"],e["id_encuentro"],
            data.numero_factura,data.concepto,
            u["numero_documento_usuario"]
        ))

        f=cur.fetchone()
        detalles=[]

        if data.incluir_prescripciones_dispensadas:
            cur.execute("""
                SELECT
                    pr.id_prescripcion,pr.cantidad,
                    m.nombre,m.precio_unitario
                FROM prescripciones pr
                JOIN medicamentos m ON m.codigo_cum=pr.codigo_cum
                WHERE pr.id_encuentro=%s
                  AND pr.estado='dispensada'
                  AND pr.is_deleted=FALSE;
            """,(e["id_encuentro"],))

            for pr in cur.fetchall():
                detalles.append((
                    pr["id_prescripcion"],None,
                    f"Medicamento: {pr['nombre']}",
                    pr["cantidad"],pr["precio_unitario"]
                ))

        if data.incluir_examenes_completados:
            cur.execute("""
                SELECT id_examen,nombre
                FROM examenes
                WHERE id_encuentro=%s
                  AND estado='completed'
                  AND is_deleted=FALSE;
            """,(e["id_encuentro"],))

            for ex in cur.fetchall():
                detalles.append((
                    None,ex["id_examen"],
                    f"Examen: {ex['nombre']}",
                    1,Decimal("0")
                ))

        for d in data.detalles_adicionales:
            detalles.append((
                None,None,d.concepto,
                d.cantidad,d.valor_unitario
            ))

        total=Decimal("0")

        for idp,idx,concepto,cantidad,valor in detalles:
            vt=Decimal(cantidad)*Decimal(valor)
            total+=vt

            cur.execute("""
                INSERT INTO factura_detalle(
                    id_factura,id_encuentro,id_prescripcion,id_examen,
                    concepto,cantidad,valor_unitario,valor_total,creado_por
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);
            """,(
                f["id_factura"],e["id_encuentro"],
                idp,idx,concepto,cantidad,
                valor,vt,u["numero_documento_usuario"]
            ))

        cur.execute("""
            UPDATE facturas
            SET total=%s,
                updated_at=now()
            WHERE id_factura=%s
            RETURNING *;
        """,(total,f["id_factura"]))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"facturas",nuevo["id_factura"],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except UniqueViolation:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya existe una factura activa para el encuentro o el número está repetido"
        )
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/facturas",tags=["Facturación"])
def listar_facturas(db=Depends(get_db),u=Depends(requerir_roles("Admin","Contable"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM facturas
            WHERE is_deleted=FALSE
            ORDER BY fecha_emision DESC;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/facturas/{id_factura}",tags=["Facturación"])
def ver_factura(id_factura:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Contable"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM facturas
            WHERE id_factura=%s
              AND is_deleted=FALSE;
        """,(id_factura,))

        f=cur.fetchone()

        if not f:
            raise HTTPException(status_code=404,detail="Factura no encontrada")

        cur.execute("""
            SELECT *
            FROM factura_detalle
            WHERE id_factura=%s
              AND is_deleted=FALSE
            ORDER BY id_detalle;
        """,(id_factura,))

        d=dict(f)
        d["detalles"]=cur.fetchall()
        return d

    finally:
        cur.close()
