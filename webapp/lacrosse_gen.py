
import re

def lfsr_digest8_reflect(message, gen, key):
    digest = 0
    for data in reversed(message):
        for i in range(8):
            if (data >> i) & 1:
                digest ^= key
            if key & 0x80:
                key = ((key << 1) ^ gen) & 0xFF
            else:
                key = (key << 1) & 0xFF
    return digest

def generate_packet(temp_f, humidity, sensor_id=0x12):
    # Temp to C
    temp_c = (temp_f - 32) * 5 / 9
    # Temp Raw: C * 10 + 500
    temp_raw = int(round(temp_c * 10)) + 500
    if temp_raw < 0: temp_raw = 0
    if temp_raw > 0xFFF: temp_raw = 0xFFF
    
    hum = int(humidity)
    if hum < 0: hum = 0
    if hum > 100: hum = 100
    
    b0 = sensor_id & 0xFF
    b1 = (temp_raw >> 8) & 0x0F # Flags are 0
    b2 = temp_raw & 0xFF
    b3 = hum & 0xFF
    
    b4 = lfsr_digest8_reflect([b0, b1, b2, b3], 0x31, 0xF4)
    
    packet_bits = ""
    for b in [b0, b1, b2, b3, b4]:
        packet_bits += "{:08b}".format(b)
    
    return packet_bits

def replace_bits_in_raw(template_timings, new_bits):
    new_timings = []
    i = 0
    bit_idx = 0
    while i < len(template_timings) - 1:
        high = template_timings[i]
        low = template_timings[i+1]
        
        # Preamble detection (750 / -720)
        if high > 600 and high < 900 and low < -600 and low > -900:
            new_timings.append(high)
            new_timings.append(low)
            i += 2
            bit_idx = 0 # Reset bit counter after preamble
            continue
            
        # Data bit detection (250 or 500 pulses)
        if high > 150 and high < 600 and low < -150 and low > -600:
            if bit_idx < len(new_bits):
                bit = new_bits[bit_idx]
                # '1': 500 high / 250 low
                # '0': 250 high / 500 low
                if bit == '1':
                    new_timings.append(500)
                    new_timings.append(-250)
                else:
                    new_timings.append(250)
                    new_timings.append(-500)
                bit_idx += 1
            else:
                # We've run out of bits for this packet, just keep original noise or skip
                new_timings.append(high)
                new_timings.append(low)
            i += 2
        else:
            # Noise/Gap
            new_timings.append(high)
            new_timings.append(low)
            i += 2
            
    # Handle last timing if odd
    if i < len(template_timings):
        new_timings.append(template_timings[i])
        
    return new_timings

def create_sub_file(template_path, temp_f, humidity):
    with open(template_path, 'r') as f:
        content = f.read()
    
    # Extract metadata
    metadata = []
    raw_data_lines = []
    for line in content.splitlines():
        if line.startswith('RAW_Data:'):
            raw_data_lines.append(line.replace('RAW_Data: ', ''))
        elif not line.startswith('RAW_Data:'):
            metadata.append(line)
            
    all_timings = []
    for line in raw_data_lines:
        all_timings.extend(map(int, line.split()))
        
    new_bits = generate_packet(temp_f, humidity)
    new_timings = replace_bits_in_raw(all_timings, new_bits)
    
    # Reconstruct RAW_Data lines (Flipper usually has ~512 timings per line)
    new_raw_lines = []
    for i in range(0, len(new_timings), 512):
        chunk = new_timings[i:i+512]
        new_raw_lines.append("RAW_Data: " + " ".join(map(str, chunk)))
        
    return "\n".join(metadata) + "\n" + "\n".join(new_raw_lines)

def generate_broadlink_payload(temp_f, humidity, repeats=6):
    packet_bits = generate_packet(temp_f, humidity)
    
    # Each bit is PWM: 1 = (500 high, 250 low), 0 = (250 high, 500 low)
    # Preamble is 4 repetitions of (750 high, 720 low)
    # We repeat the entire 40-bit packet sequence 6 times with a gap of 10ms.
    
    one_packet_pulses = []
    # Preamble
    for _ in range(4):
        one_packet_pulses.extend([750, 720])
    
    # Data
    for bit in packet_bits:
        if bit == '1':
            one_packet_pulses.extend([500, 250])
        else:
            one_packet_pulses.extend([250, 500])
            
    # Assemble final pulse train
    all_pulses = []
    for i in range(repeats):
        all_pulses.extend(one_packet_pulses)
        if i < repeats - 1:
            all_pulses.append(10000) # 10ms gap (low) - wait, Broadlink alternates.
            # If the last data bit ended in a low pulse, we need to extend it.
            # But La Crosse data bits always end in a low pulse.
            # So the last pulse in one_packet_pulses is low.
            # We want to add 10ms of low.
            # Broadlink format: high, low, high, low...
            # Since one_packet_pulses has an even number of elements, 
            # the last element is low.
            # So the next element in all_pulses must be high.
            # This is tricky. Let's make sure the sequence always starts with high.
            # The preamble starts with high (750).
            # If the last element was low, the next must be high.
            # To add 10ms of low, we should add it to the LAST element of the packet.
            all_pulses[-1] += 10000
            
    # Convert to Broadlink ticks
    # ticks = duration_us * 269 / 8192
    payload_data = bytearray()
    for duration in all_pulses:
        ticks = int(round(duration * 269 / 8192))
        if ticks > 255:
            payload_data.append(0x00)
            payload_data.append((ticks >> 8) & 0xFF)
            payload_data.append(ticks & 0xFF)
        else:
            payload_data.append(ticks)
            
    # Broadlink RF Header: 0xb2, repeats, length_le
    header = bytearray([0xb2, 0x00]) # We handled repeats in the pulse train
    length = len(payload_data)
    header.append(length & 0xFF)
    header.append((length >> 8) & 0xFF)
    
    return header + payload_data
