"""Tool Port - Interface for tool implementations.

Defines the contract that tool adapters must follow.
The domain depends on this abstraction, not on specific tool frameworks.
"""

from __future__ import annotations

from typing import Any, List, Dict, Optional, Protocol
from langchain_core.tools import StructuredTool


class ToolPort(Protocol):
    """Protocol defining the tool interface for the domain layer.
    
    This protocol specifies what the domain layer expects from tools,
    without knowing about LangChain's @tool decorator specifics.
    """
    
    def get_tools(self) -> List[StructuredTool]:
        """Get the list of available tools.
        
        Returns:
            List of StructuredTool instances ready for LLM binding
        """
        ...
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get the JSON schema for a specific tool.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Dict with the tool's parameter schema, or None if not found
        """
        ...
    
    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Execute a specific tool with given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            args: Dictionary of arguments matching the tool's schema
            
        Returns:
            String result from the tool execution
        """
        ...
