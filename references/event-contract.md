# Event Contract

Baseline source:
`../../spec/13-事件与模块接口规范.md`

## Naming Convention

Use:
1. `<domain>.<object>`
2. `<domain>.<object>.<action>`

Example domains:
1. `net`
2. `mqtt`
3. `tcp`
4. `sms`
5. `gnss`
6. `wifi`
7. `sys`

## Payload Style

1. Include timestamp field (`ts`) where useful.
2. Keep keys short and stable.
3. Keep error payloads explicit:
   `error`, `reason`, `when`.

## Frequency Control

1. Add minimum interval for high-frequency events.
2. Debounce signal/health events to avoid log flooding.
