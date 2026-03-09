# Coding Spec

## Architecture Guidelines

1. Keep modules focused:
   one module for one responsibility.
2. Separate concerns:
   device bootstrap, network init, protocol client, business logic, persistence.
3. Use composition over deep inheritance.
4. Keep handlers and callbacks lightweight.

## Interface and Error Design

1. Define stable function contracts:
   inputs, return, retry behavior, and error paths.
2. Explicitly classify errors:
   retryable vs non-retryable.
3. Include context in logs:
   module, step, error code/message.

## Performance and Reliability

1. Keep memory usage predictable.
2. Avoid unbounded buffers and large temporary objects.
3. Use controlled polling intervals and timer cadence.
4. Add watchdog/health checks where required by product profile.

## Event and Message Style

1. Keep topic names consistent and predictable.
2. Keep payload fields stable across versions.
3. Add throttling/debouncing for high-frequency events.
