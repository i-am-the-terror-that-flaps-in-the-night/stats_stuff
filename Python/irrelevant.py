#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module Docstring: This script calculates squares
"""

from typing import Generator, List, Optional, Union

# Global constant (Built-in types and numbers)
MAX_RETRIES: int = 42
PI_APPROX: float = 3.14159
HEX_VAL: int = 0xFF
BOOLEAN_FLAG: bool = True
NONE_TYPE: Optional[object] = None


class SyntaxShowcase:
    """Class docstring demonstrating OOP highlighting."""

    def __init__(self, name: str) -> None:
        self.name: str = name
        self._private_var: int = 100  # Conventional private variable

    @property
    def upper_name(self) -> str:
        """Decorator and string manipulation highlighting."""
        return self.name.upper()

    async def compute_meaning(self, factor: float) -> Union[float, int]:
        """Asynchronous method with exception handling."""
        try:
            # Format strings (f-strings) and operators
            print(f"Calculating for {self.name}...")
            if factor == 0:
                raise ValueError("Factor cannot be zero.")

            result = (self._private_var * factor) ** 2
            return result
        except ValueError as e:
            print(f"Caught an expected error: {e}")
            return len(self.name)  # Built-in function
        finally:
            print("Cleanup operations here.")


def structural_pattern_matching(value: int) -> str:
    """Showcases Python 3.10+ match-case syntax."""
    match value:
        case 1 | 2 | 3:
            return "Low range"
        case _ if value > 10:
            return "High range"
        case _:
            return "Default"


def generator_example(limit: int) -> Generator[int, None, None]:
    """Yield keyword highlighting."""
    for i in range(limit):
        if i % 2 == 0:
            yield i


# Main execution block to test control flow
if __name__ == "__main__":
    # Context manager highlighting
    with open(__file__, mode="r", encoding="utf-8") as current_file:
        content: str = current_file.read()

    # Lambda functions and list comprehensions
    square_lambda = lambda x: x * x
    numbers: List[int] = [1, 2, 3, 4, 5]
    squares: List[int] = [square_lambda(n) for n in numbers if n % 2 != 0]

    # Instantiate and run async code
    showcase = SyntaxShowcase(name="HighlightTest")

    # Simple console output check
    print(f"Processed squares: {squares}")
