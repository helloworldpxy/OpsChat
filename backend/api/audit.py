# -*- coding: utf-8 -*-
"""
审计日志API接口
查询和管理审计日志
"""

import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_async_session
from ..models.audit import AuditLog, Conversation, ConversationMessage
from ..core.chain_of_thought import cot_manager

logger = logging.getLogger(__name__)

router = APIRouter()


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
                    query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(start_time))
                if end_time:
                    query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(end_time))
                
                query = query.order_by(AuditLog.timestamp.desc())
                
                total = query.count()
                db_logs = query.offset((page - 1) * page_size).limit(page_size).all()
                logs = [log.to_dict() for log in db_logs]
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"从数据库读取审计日志失败，回退到内存数据: {e}")
            logs = []
        
        # 如果数据库没有数据，回退到内存
        if not logs:
            for tid, stages in cot_manager.traces.items():
                if trace_id and tid != trace_id:
                    continue
                for stage_data in stages:
                    if stage and stage_data.stage != stage:
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
        
        # 分页
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_logs = logs[start_idx:end_idx]
        
        return {
            "success": True,
            "data": paginated_logs,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
        
    except Exception as e:
        logger.error(f"获取审计日志失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces")
async def get_traces():
    """
    获取所有追踪列表
    
    Returns:
        追踪列表
    """
    try:
        traces = []
        
        # 从内存获取
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
