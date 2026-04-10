# SKILL.md

name: ai-native-architecture
description: Enforces stateless object-oriented design and RORO (Receive an Object, Return an Object) patterns to maximize AI context comprehension and prevent state hallucinations.

## Core Directives

1. **Stateless Classes**: Classes MUST NOT maintain implicit mutable state (e.g., do not mutate `self.state` or `self.current_target` within methods). Use classes strictly for dependency injection, routing, or defining Strategy Pattern interfaces.
2. **Data/Logic Separation**: Define all state using `pydantic.BaseModel` or `@dataclass(frozen=True)`.
3. **The RORO Pattern**: Core business logic methods within classes MUST receive explicit state objects as arguments and return new state objects (or modified copies). Never rely on internal instance variables for computation.
4. **I/O Isolation**: Pure calculation logic must be completely isolated from side effects (Network, DB, File System). I/O operations must be handled at the outermost boundaries of the application.
