"""
事件系统模块
============
提供事件总线和事件类型定义，用于组件间通信
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Any, Callable, Optional
from datetime import datetime
from collections import defaultdict
import threading


class EventType(Enum):
    """事件类型枚举"""

    # 信号事件
    SIGNAL_GENERATED = auto()
    SIGNAL_EXECUTED = auto()
    SIGNAL_CANCELLED = auto()

    # 交易事件
    ORDER_SUBMITTED = auto()
    ORDER_FILLED = auto()
    ORDER_REJECTED = auto()

    # 持仓事件
    POSITION_OPENED = auto()
    POSITION_CLOSED = auto()
    POSITION_UPDATED = auto()

    # 市场事件
    BAR_CLOSED = auto()
    TICK_RECEIVED = auto()
    SESSION_START = auto()
    SESSION_END = auto()

    # 回测事件
    BACKTEST_START = auto()
    BACKTEST_END = auto()
    BACKTEST_PROGRESS = auto()

    # 优化事件
    OPTIMIZATION_START = auto()
    OPTIMIZATION_END = auto()
    OPTIMIZATION_TRIAL_COMPLETE = auto()
    OPTIMIZATION_BEST_UPDATED = auto()

    # 错误事件
    ERROR_OCCURRED = auto()
    WARNING_ISSUED = auto()


@dataclass
class Event:
    """事件数据结构"""

    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = field(default="")
    data: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """获取事件数据"""
        return self.data.get(key, default)


class EventBus:
    """事件总线 - 支持发布/订阅模式"""

    def __init__(self):
        self._handlers: Dict[EventType, List[Callable[[Event], None]]] = defaultdict(
            list
        )
        self._global_handlers: List[Callable[[Event], None]] = []
        self._lock = threading.RLock()
        self._event_history: List[Event] = []
        self._max_history: int = 1000

    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]):
        """订阅特定事件类型"""
        with self._lock:
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Callable[[Event], None]):
        """订阅所有事件"""
        with self._lock:
            if handler not in self._global_handlers:
                self._global_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], None]):
        """取消订阅"""
        with self._lock:
            if event_type in self._handlers:
                if handler in self._handlers[event_type]:
                    self._handlers[event_type].remove(handler)

    def unsubscribe_all(self, handler: Callable[[Event], None]):
        """取消订阅所有事件"""
        with self._lock:
            if handler in self._global_handlers:
                self._global_handlers.remove(handler)
            for handlers in self._handlers.values():
                if handler in handlers:
                    handlers.remove(handler)

    def emit(self, event: Event):
        """发布事件"""
        # 记录历史
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

        # 调用特定类型的处理器
        handlers = self._handlers.get(event.event_type, []).copy()
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"Error handling event {event.event_type}: {e}")

        # 调用全局处理器
        global_handlers = self._global_handlers.copy()
        for handler in global_handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"Error in global event handler: {e}")

    def emit_new(self, event_type: EventType, source: str = "", **data):
        """创建并发布新事件"""
        event = Event(event_type=event_type, source=source, data=data)
        self.emit(event)

    def get_history(
        self, event_type: Optional[EventType] = None, limit: int = 100
    ) -> List[Event]:
        """获取事件历史"""
        with self._lock:
            events = self._event_history
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            return events[-limit:]

    def clear_history(self):
        """清空事件历史"""
        with self._lock:
            self._event_history.clear()


# 全局事件总线
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局事件总线"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def reset_event_bus():
    """重置全局事件总线"""
    global _global_event_bus
    _global_event_bus = EventBus()
