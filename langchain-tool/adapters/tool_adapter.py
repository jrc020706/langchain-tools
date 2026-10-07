"""Tool Adapter - Concrete implementation of ToolPort.

Wraps the LangChain tools from tools.py and exposes them through
the ToolPort protocol defined in ports/tool_port.py.
The domain layer (ChatUseCase) depends on ToolPort abstraction,
not on the specific LangChain tool implementations.
"""

from __future__ import annotations

from typing import Any, List, Dict, Optional
from ports.tool_port import ToolPort
from langchain_core.tools import StructuredTool

# Import tools from the original tools module
from tools import TOOLS as ORIGINAL_TOOLS


class ToolAdapter(ToolPort):
    """Concrete adapter for medication guidance tools.
    
    Wraps the 8 tools from tools.py (analizar_sintomas, buscar_medicamento, etc.)
    and exposes them through the ToolPort protocol.
    
    The domain layer only knows about the ToolPort interface,
    not about how tools are implemented or what data they use internally.
    """
    
    def __init__(self):
        """Initialize the tool adapter with original tools."""
        # Convert original LangChain @tool decorated functions to StructuredTool
        self._tools: List[StructuredTool] = [
            self._convert_to_structured(tool) for tool in ORIGINAL_TOOLS
        ]
    
    def _convert_to_structured(self, tool: Any) -> StructuredTool:
        """Convert a LangChain @tool decorated function to StructuredTool.
        
        Args:
            tool: A function decorated with @tool from tools.py
            
        Returns:
            StructuredTool instance with name, description, and args_schema
        """
        from langchain_core.tools import tool
        
        # If it's already a StructuredTool, return as-is
        if hasattr(tool, 'name') and hasattr(tool, 'description'):
            return tool
        
        # Otherwise, try to get the decoratd function
        func = getattr(tool, 'func', tool)
        
        # Create a new @tool decorated function
        # LangChain's @tool decorator creates a StructuredTool
        decorated = tool(func)
        
        return decorated
    
    def get_tools(self) -> List[StructuredTool]:
        """Get the list of available tools.
        
        Returns:
            List of StructuredTool instances (8 medication tools)
        """
        return self._tools
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get the JSON schema for a specific tool.
        
        Args:
            tool_name: Name of the tool (e.g., "analizar_sintomas")
            
        Returns:
            Dict with the tool's parameter schema, or None if not found
        """
        for tool in self._tools:
            if tool.name == tool_name:
                if hasattr(tool, 'args_schema') and tool.args_schema:
                    return tool.args_schema.model_json_schema()
                # Fallback: return basic info from description
                return {
                    "name": tool_name,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
        return None
    
    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Execute a specific tool with given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            args: Dictionary of arguments matching the tool's schema
            
        Returns:
            String result from the tool execution
            
        Raises:
            ValueError: If tool_name is not found
        """
        for tool in self._tools:
            if tool.name == tool_name:
                try:
                    # Invoke the tool with the provided arguments
                    result = tool.invoke(args)
                    if hasattr(result, 'content'):
                        return str(result.content)
                    return str(result)
                except Exception as e:
                    return f"Error executing {tool_name}: {str(e)}"
        
        raise ValueError(f"Tool '{tool_name}' not found in available tools")
    
    def get_tool_descriptions(self) -> List[Dict[str, str]]:
        """Get descriptions of all available tools.
        
        Returns:
            List of dicts with 'name' and 'description' keys
        """
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools
        ]


# Factory function
def create_tool_adapter() -> ToolPort:
    """Factory to create a ToolPort instance.
    
    Returns:
        ToolAdapter instance implementing the ToolPort protocol
    """
    return ToolAdapter()
