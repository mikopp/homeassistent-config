# Scripts and scenes

Part of the `yaml` skill (general HA style; this repo's binding rules: `.claude/rules/ha-yaml.md`).

## Scripts

### Script Modes

Same as automation modes: `single`, `restart`, `queued`, `parallel`

### Script Fields (Parameters)

```yaml
script:
  notify_user:
    alias: "Notify User"
    fields:
      message:
        name: Message
        required: true
        selector:
          text:
      title:
        name: Title
        default: "Home Assistant"
        selector:
          text:
    sequence:
      - action: notify.mobile_app
        data:
          title: "{{ title }}"
          message: "{{ message }}"
```

### Calling Scripts

```yaml
# Method 1: Direct call (blocking - waits for completion)
action:
  - action: script.notify_user
    data:
      message: "Alert!"

# Method 2: script.turn_on (non-blocking - continues immediately)
action:
  - action: script.turn_on
    target:
      entity_id: script.notify_user
    data:
      variables:
        message: "Alert!"
```

---

## Scenes

### When to Use

| Component | Use When |
|-----------|----------|
| **Scene** | Setting multiple devices to specific states simultaneously |
| **Script** | Reusable action sequences called from multiple places |
| **Automation** | Event-driven responses requiring triggers |

### Scene Snapshots (Save/Restore)

```yaml
# Save current state before change
- action: scene.create
  data:
    scene_id: before_window_open
    snapshot_entities:
      - climate.ecobee
      - light.ceiling_lights

# Later, restore saved state
- action: scene.turn_on
  target:
    entity_id: scene.before_window_open
```

**Common use cases:**
- Window open/close (save HVAC state, restore on close)
- Cleaning mode (all lights 100%, then restore)
- Doorbell notification (flash lights, then restore)
- TV/Media playback (dim lights, restore after)
