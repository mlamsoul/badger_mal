import badger2040
from badger2040 import WIDTH, HEIGHT
from machine import RTC
from umqtt.simple import MQTTClient
import network
import time
import utime
import ntptime
import jpegdec
import binascii
import gc
import WIFI_CONFIG
import MQTT_CONFIG
import HOME_ASSISTANT
import urequests

# Starting and end time of your preferrered power schedule and the max duration of a full wash
HEURE_DEBUT = 22
HEURE_FIN = 7
DUREE_MAX = 4

LINE_HEIGHT = 16
X_TXT = 104
JOUR_SEM = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
MONTH = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
BLACK = 0
WHITE = 15
PM_CST = {16: 'PM_NONE', 10555714: 'PM_PERFORMANCE', 17: 'PM_POWERSAVE'}

previous_answer = None

# Constant for the daylight saving for the next 10 years
# see https://www.epochconverter.com/
DAYLIGHT = [
    1711846800, # 2024-03-31 01:00:00 / 2024-10-27 02:00:00
    1729994400,
    1743296400, # 2025 03-30 01:00:00 / 2025-10-28 02:00:00
    1761444000,
    1774746000, # 2026-03-29 01:00:00 / 2026-10-25 02:00:00
    1792893600,
    1806195600, # 2027-03-28 01:00:00 / 2027-10-31 02:00:00
    1824948000,
    1837645200, # 2028-03-26 01:00:00 / 2028-10-29 02:00:00
    1856397600,
    1869094800, # 2029-03-25 01:00:00 / 2029-10-28 02:00:00
    1887847200,
    1901149200, # 2030-03-31 01:00:00 / 2030-10-27 02:00:00
    1919296800,
    1932598800, # 2031-03-30 01:00:00 / 2031-10-26 02:00:00
    1950746400,
    1964091600, # 2032-03-28 01:00:00 / 2032-10-31 02:00:00
    1982844000,
    1995541200, # 2033-03-27 01:00:00 / 2033-10-30 02:00:00
    2014293600,
    2026990800, # 2034-03-26 01:00:00 / 2034-10-29 02:00:00
    2045743200,
]
GMT = 1
DAYLIGHT_SHIFT = [GMT+1, GMT]*10

# Display Setup
display = badger2040.Badger2040()
display.led(0)

# Clear the screen ... lol
def clear_screen():
    display.set_pen(WHITE)
    display.clear()
    display.set_pen(BLACK)

# Display some network info (used as startup screen to check that the setup is correct)
def show_net_info():
    clear_screen()
    ips = wlan.ifconfig()
    mac = binascii.hexlify(wlan.config('mac'),':').decode()
    gc.collect()
    display.text(f"ssid : {wlan.config('ssid')}  (ch : {wlan.config('channel')}) {network.country()}", 0, 0*LINE_HEIGHT, scale=2)
    display.text(f"ip : {ips[0]}", 0, 1*LINE_HEIGHT, scale=2)
    display.text(f"dns : {ips[3]}", 0, 2*LINE_HEIGHT, scale=2)
    display.text(f"mac : {mac}", 0, 3*LINE_HEIGHT, scale=2)
    display.text(f"hostname : {network.hostname()}", 0, 4*LINE_HEIGHT, scale=2)
    display.text(f"connected : {wlan.isconnected()}", 0, 5*LINE_HEIGHT, scale=2)
    display.text(f"active : {wlan.active()}", 0, 6*LINE_HEIGHT, scale=2)
    display.text(f"Power mgmt : {PM_CST[wlan.config('pm')]}", 0, 7*LINE_HEIGHT, scale=2)
    display.update()
    time.sleep(2)

# Connect to the WIFI network  (TODO: move to a function)
# and fetch the date & time from NTP (universal time)
try:
    display.set_update_speed(badger2040.UPDATE_FAST)
    clear_screen()
    display.update()
    
    wlan = network.WLAN(network.STA_IF)  # = station vs AP_IF = access point
    network.country(WIFI_CONFIG.COUNTRY)
    wlan.active(True)
    wlan.connect(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK)
    while not wlan.isconnected() and wlan.status() >= 0:
        print("Connecting...")
        time.sleep(0.2)
    gc.collect()
    print(gc.mem_free())
    
    if display.isconnected():
        print(wlan.ifconfig()[0])
        #ntptime.host = "be.pool.ntp.org"
        ntptime.timeout = 2
        ntptime.settime()
except RuntimeError as rte:
    print(f"RuntimeError: {rte.value}")
except OSError as ose:
    print(f"ntptime.settime OSError: {ose}")

# Calc a shift in second according to the GMT and day light saving
# For example, for GMT+1 and 1h daylight => (1+1)*3600 = 7200s
def calc_daylight() -> int:
    table = zip(DAYLIGHT, DAYLIGHT_SHIFT)
    f = [v for v in table if (v[0] < utime.time())]
    return f[-1][1]*3600

# Update the RTC (real-time clock) with the gmt/daylight fixed time
rtc = RTC()
year, month, day, hour, minute, second, weekday, yearday =  utime.localtime(utime.time()+calc_daylight())
rtc.datetime((year, month, day, weekday, hour, minute, second, yearday))

# Format the information message about your power schedule (adapt to your need)
def calc_regime() -> str:
    weekday =  rtc.datetime()[3]
    if weekday < 4:
        return "après {}h, avant {}h".format(HEURE_DEBUT, HEURE_FIN)
    elif weekday == 4:
        return "après {}h".format(HEURE_DEBUT, HEURE_FIN)
    else:
        return "toute la journée"

# Format the message about the programmation
def calc_prog(hour, weekday) -> str:
    if hour >= HEURE_DEBUT or hour <= HEURE_FIN-DUREE_MAX or weekday > 4:
        return "maintenant"
    else:
        return "dans {} heure{}".format(HEURE_DEBUT + 4 - hour, 's' if (HEURE_DEBUT + 4 - hour) > 1 else '')

# Display the wash machine image
def draw_image() -> None:
    jpeg = jpegdec.JPEG(display.display)
    jpeg.open_file('/images/mac_laver.jpg')
    jpeg.decode(0, 25)

# Display the date and the time at the top in reverse
def draw_day_time() -> None:
    display.set_pen(BLACK)
    display.rectangle(0, 0, WIDTH, 20)
    display.set_pen(WHITE)

    month, day, weekday, hour, minute =  rtc.datetime()[1:6]
    heure = "{:02}:{:02}".format(hour, minute)

    display.text("{} {} {}".format(JOUR_SEM[weekday], day, MONTH[month-1]), 3, 4)
    display.text(heure,  WIDTH - display.measure_text(heure) - 4, 4, WIDTH)
    display.set_pen(BLACK)

# Push the suggestion message to Home Assistant (optional and either via webhook or via mqtt)
def push_HA(answer, mqttclient) -> None:
    global previous_answer
    if previous_answer != answer:
        previous_answer = answer
        hour, minute, second =  rtc.datetime()[4:7]
        print(f"{hour}:{minute:02d}:{second:02d} {answer}")
        json = {"msg":answer}
        try:
            urequests.request('POST', f'{HOME_ASSISTANT.PROTOCOL}://{HOME_ASSISTANT.HOSTNAME}/api/webhook/badger2040w', json=json)
        except Exception as e:
            print(f"{hour}:{minute:02d}:{second:02d} Exception in push_HA : {type(e).__name__}{e.args}")
            
        try:
            mqttclient.connect()
            mqttclient.publish('badger/msg', answer, qos=0)
            mqttclient.disconnect()
            
        except Exception as e:
            print(f"{hour}:{minute:02d}:{second:02d} Exception in push_HA : {type(e).__name__}{e.args}")
            # EPERM=1, EAGAIN = 11, EIO = 5, EINVAL=22, ENODEV=19, EOPNOTSUPP=95, ECONNABORTED=103, ETIMEDOUT=110, EHOSTUNREACH=113

# Display the wash machine starting time suggestion
def draw_suggestion() -> str:
    display.set_pen(WHITE)
    display.rectangle(X_TXT-7, 24, WIDTH, HEIGHT)
    display.set_pen(BLACK)

    display.text(calc_regime(), X_TXT-7, 28)
    display.set_font("cursive")
    display.set_thickness(3)

    weekday, hour =  rtc.datetime()[3:5]
    answer = calc_prog(hour, weekday)

    msg = "démarrer" if answer=="maintenant" else "programmer"
    display.text(msg, X_TXT, 70, scale=1)
    scale = (WIDTH-X_TXT) / display.measure_text(answer, spacing=0, scale=1)
    display.text("{}".format(answer), X_TXT, 100, scale=min(scale,1))
    display.set_font("bitmap6")
    return answer

# Init MQTT (optional - only you use it for HA)
def mqtt_init() -> MQTTClient:
    return MQTTClient(
        client_id = MQTT_CONFIG.MQTT_CLIENT_ID,
        server = MQTT_CONFIG.MQTT_SERVER,
        port = MQTT_CONFIG.MQTT_PORT,
        user = MQTT_CONFIG.MQTT_USER,
        password = MQTT_CONFIG.MQTT_PASSWORD,
        keepalive = MQTT_CONFIG.MQTT_KEEPALIVE,
        ssl = MQTT_CONFIG.MQTT_SSL,
        ssl_params = MQTT_CONFIG.MQTT_SSL_PARAMS)
    
def main() -> None:
    clear_screen()
    draw_image()
    show_net_info()
    clear_screen()
    draw_image()
    mqttclient = mqtt_init()

    while True:
        draw_day_time()
        answer = draw_suggestion()
        push_HA(answer, mqttclient)
        display.update()
        badger2040.sleep_for(1)
        gc.collect()
main()
