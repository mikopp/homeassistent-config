The Recommended YAML Workaround
Instead of using a raw input_number, you can create a Template Number (or Select/Switch) directly in your configuration.yaml. This acts as a wrapper that can be assigned to your "Pergola Dach" device. 
Home Assistant
Home Assistant
 +1
yaml
template:
  - device:
      name: "Pergola Dach"
      identifiers: "pergola_dach_virtual_device"
      manufacturer: "Custom YAML"
      model: "Virtual Controls"
    
    # This creates a number slider directly assigned to the device
    number:
      - name: "Dach Position"
        unique_id: "pergola_dach_pos_helper"
        state: "{{ states('input_number.pergola_dach_pos_backend') | float(0) }}"
        set_value:
          action: input_number.set_value
          target:
            entity_id: input_number.pergola_dach_pos_backend
          data:
            value: "{{ value }}"
        step: 1
        min: 0
        max: 100
Use code with caution.

Why this works:
Device Assignment: The device: block at the top of the template: section automatically groups every entity defined below it into that specific device.
Back-end Helper: You still have an input_number in the background (which holds the actual value), but you interact with the Template Number on your dashboard.
No UI Needed: Since everything is defined in the Template integration YAML, the device and its entities are generated correctly every time you reload your configuration. 
Home Assistant
Home Assistant
 +1