# -*- coding: utf-8 -*-
"""
审计日志API接口
查询和管理审计日志
"""

import logging
import csv
import io
import json
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_async_session
from ..models.audit import AuditLog, Conversation, ConversationMessage
from ..core.chain_of_thought import cot_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_cell(value) -> str:
    """CSV 单元格防护：防止公式注入（Excel 将 = + - @ 开头当公式执行）"""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _parse_time(value: str, field: str) -> datetime:
    """解析 ISO8601 时间参数，非法时返回 400（而非 500）"""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} 格式非法，需 ISO8601（如 2026-08-19T00:00:00）")
    return dt.replace(tzinfo=None)  # 库内为无时区 UTC，统一去时区再比较


@router.get("/logs")
async def get_audit_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    trace_id: Optional[str] = Query(None, description="追踪ID"),
    stage: Optional[str] = Query(None, description="阶段名称"),
    start_time: Optional[str] = Query(None, description="开始时间"),
    end_time: Optional[str] = Query(None, description="结束时间"),
):
    """
    获取审计日志列表
    
    Args:
        page: 页码
        page_size: 每页数量
        trace_id: 追踪ID过滤
        stage: 阶段名称过滤
        start_time: 开始时间过滤
        end_time: 结束时间过滤
        
    Returns:
        审计日志列表
    """
    try:
        logs = []
        
        # 优先从数据库读取（持久化数据）
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                query = db.query(AuditLog)
                if trace_id:
                    query = query.filter(AuditLog.trace_id == trace_id)
                if stage:
                    query = query.filter(AuditLog.stage == stage)
                if start_time:
                    query = query.filter(AuditLog.timestamp >= _parse_time(start_time, "start_time"))
                if end_time:
                    query = query.filter(AuditLog.timestamp <= _parse_time(end_time, "end_time"))
                
                query = query.order_by(AuditLog.timestamp.desc())
                
                total = query.count()
                db_logs = query.offset((page - 1) * page_size).limit(page_size).all()
                logs = [log.to_dict() for log in db_logs]
            finally:
                db.close()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"从数据库读取审计日志失败，回退到内存数据: {e}")
            logs = []
        
        # 如果数据库没有数据，回退到内存（与 DB 路径应用一致的过滤）
        if not logs:
            start_dt = _parse_time(start_time, "start_time") if start_time else None
            end_dt = _parse_time(end_time, "end_time") if end_time else None
            for tid, stages in cot_manager.traces.items():
                if trace_id and tid != trace_id:
                    continue
                for stage_data in stages:
                    if stage and stage_data.stage != stage:
                        continue
                    ts = stage_data.timestamp
                    if start_dt and ts < start_dt:
                        continue
                    if end_dt and ts > end_dt:
                        continue
                    logs.append({
                        "trace_id": tid,
                        "stage": stage_data.stage,
                        "content": stage_data.content,
                        "timestamp": stage_data.timestamp.isoformat(),
                        "details": stage_data.details,
                    })
            
            logs.sort(key=lambda x: x["timestamp"], reverse=True)
            total = len(logs)
            # 内存数据才需要在此分页（DB 路径已在上游分页）
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            logs = logs[start_idx:end_idx]
        
        return {
            "success": True,
            "data": logs,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取审计日志失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export")
async def export_audit_logs(
    format: str = Query("csv", description="导出格式: csv / json"),
    trace_id: Optional[str] = Query(None, description="追踪ID过滤"),
    stage: Optional[str] = Query(None, description="阶段名称过滤"),
    start_time: Optional[str] = Query(None, description="开始时间"),
    end_time: Optional[str] = Query(None, description="结束时间"),
):
    """
    导出审计日志（JSON / CSV 文件下载）
    复用 /logs 的过滤逻辑，一次导出全部匹配记录（不分页）
    """
    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail=f"不支持的导出格式: {format}")

    try:
        logs = []

        # 优先从数据库读取（持久化数据）
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                query = db.query(AuditLog)
                if trace_id:
                    query = query.filter(AuditLog.trace_id == trace_id)
                if stage:
                    query = query.filter(AuditLog.stage == stage)
                if start_time:
                    query = query.filter(AuditLog.timestamp >= _parse_time(start_time, "start_time"))
                if end_time:
                    query = query.filter(AuditLog.timestamp <= _parse_time(end_time, "end_time"))

                rows = query.order_by(AuditLog.timestamp.asc()).all()
                logs = [log.to_dict() for log in rows]
            finally:
                db.close()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"从数据库读取审计日志失败，回退到内存数据: {e}")

        # 数据库无持久化数据时回退到内存（与 DB 路径应用一致的过滤）
        if not logs:
            start_dt = _parse_time(start_time, "start_time") if start_time else None
            end_dt = _parse_time(end_time, "end_time") if end_time else None
            for tid, stages in cot_manager.traces.items():
                if trace_id and tid != trace_id:
                    continue
                for stage_data in stages:
                    if stage and stage_data.stage != stage:
                        continue
                    ts = stage_data.timestamp
                    if start_dt and ts < start_dt:
                        continue
                    if end_dt and ts > end_dt:
                        continue
                    logs.append({
                        "trace_id": tid,
                        "stage": stage_data.stage,
                        "content": stage_data.content,
                        "timestamp": stage_data.timestamp.isoformat(),
                        "details": stage_data.details,
                    })
            logs.sort(key=lambda x: x["timestamp"], reverse=True)

        filename = f"audit_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if format == "json":
            payload = json.dumps({"success": True, "count": len(logs), "data": logs},
                                 ensure_ascii=False, indent=2)
            return Response(
                content=payload,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
            )

        # CSV
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "timestamp", "trace_id", "stage", "stage_order", "content",
            "risk_level", "security_decision", "rules_triggered",
            "tool_name", "tool_params", "tool_result",
            "user_confirmed", "session_id", "created_at",
        ])
        for log in logs:
            writer.writerow([
                _safe_cell(log.get("timestamp")),
                _safe_cell(log.get("trace_id")),
                _safe_cell(log.get("stage")),
                _safe_cell(log.get("stage_order")),
                _safe_cell((log.get("content") or "").replace("\r", " ").replace("\n", " ")),
                _safe_cell(log.get("risk_level")),
                _safe_cell(log.get("security_decision")),
                _safe_cell(json.dumps(log.get("rules_triggered") or [], ensure_ascii=False)),
                _safe_cell(log.get("tool_name")),
                _safe_cell(json.dumps(log.get("tool_params") or {}, ensure_ascii=False)),
                _safe_cell((log.get("tool_result") or "").replace("\r", " ").replace("\n", " ")),
                _safe_cell(log.get("user_confirmed")),
                _safe_cell(log.get("session_id")),
                _safe_cell(log.get("created_at")),
            ])

        content = "\ufeff" + buffer.getvalue()  # UTF-8 BOM，Excel 直接打开不乱码
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出审计日志失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces")
async def get_traces():
    """
    获取所有追踪列表（轨迹视图）
    优先从数据库按 trace_id 聚合，重启后数据仍可导航；无持久化时回退内存

    Returns:
        追踪列表
    """
    try:
        traces = []
        db_traces = []

        # 数据库聚合（按 trace_id 分组）
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                rows = db.query(
                    AuditLog.trace_id,
                    func.min(AuditLog.timestamp).label("start_time"),
                    func.max(AuditLog.timestamp).label("end_time"),
                    func.count(AuditLog.id).label("stage_count"),
                ).group_by(AuditLog.trace_id).order_by(
                    desc(func.max(AuditLog.timestamp))
                ).all()

                for r in rows:
                    stage_rows = db.query(AuditLog.stage).filter(
                        AuditLog.trace_id == r.trace_id
                    ).order_by(AuditLog.stage_order.asc()).all()
                    first_log = db.query(AuditLog).filter(
                        AuditLog.trace_id == r.trace_id
                    ).order_by(AuditLog.stage_order.asc()).first()
                    db_traces.append({
                        "trace_id": r.trace_id,
                        "exists": True,
                        "start_time": r.start_time.isoformat() if r.start_time else None,
                        "end_time": r.end_time.isoformat() if r.end_time else None,
                        "stage_count": r.stage_count,
                        "stages": [s[0] for s in stage_rows],
                        "title": (first_log.content or "")[:60] if first_log else "",
                    })
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"从数据库读取追踪列表失败，回退内存: {e}")
            db_traces = []

        if db_traces:
            return {
                "success": True,
                "data": db_traces,
                "total": len(db_traces),
            }

        # 回退到内存
        for trace_id in cot_manager.traces:
            summary = cot_manager.get_trace_summary(trace_id)
            traces.append(summary)

        return {
            "success": True,
            "data": traces,
            "total": len(traces),
        }

    except Exception as e:
        logger.error(f"获取追踪列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trace/{trace_id}")
async def get_trace_detail(trace_id: str):
    """
    获取追踪详情
    
    Args:
        trace_id: 追踪ID
        
    Returns:
        追踪详情
    """
    try:
        # 从数据库读取
        try:
            from ..database import SessionLocal
            from ..models.audit import AuditLog
            
            db = SessionLocal()
            try:
                db_logs = db.query(AuditLog).filter(
                    AuditLog.trace_id == trace_id
                ).order_by(AuditLog.stage_order).all()
                
                if db_logs:
                    return {
                        "success": True,
                        "data": {
                            "trace_id": trace_id,
                            "stages": [log.to_dict() for log in db_logs],
                        },
                    }
            finally:
                db.close()
        except Exception:
            pass
        
        # 回退到内存
        trace = cot_manager.get_trace(trace_id)
        if not trace:
            raise HTTPException(status_code=404, detail=f"追踪不存在: {trace_id}")
        
        return {
            "success": True,
            "data": {
                "trace_id": trace_id,
                "stages": trace,
            },
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取追踪详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/traces")
async def clear_traces():
    """
    清除所有追踪
    
    Returns:
        操作结果
    """
    try:
        cot_manager.clear_all()
        
        # 同时清理数据库
        try:
            from ..database import SessionLocal
            from ..models.audit import AuditLog
            db = SessionLocal()
            try:
                db.query(AuditLog).delete()
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"清理数据库审计日志失败: {e}")
        
        return {
            "success": True,
            "message": "所有追踪已清除",
        }
        
    except Exception as e:
        logger.error(f"清除追踪失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
