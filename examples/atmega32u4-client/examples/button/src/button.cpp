#include <Button.h>
#include <logger.h>
#include <event_timer.h>

Button buttonA(14);

Logger espLogger;

EventTimer timer;

void setup() 
{
    Serial.begin(115200);
    
    espLogger.initLog();

    buttonA.init();

    Serial.println("/setup()");

    timer.start(20);
}

/**
 * This basic example sends the time (from millis()) every
 * five seconds. See the `readme.md` in the root directory of this repo for 
 * how to set up the WiFi. 
 * */
void loop() 
{
    static uint32_t lastSend = 0;
    uint32_t currTime = millis();
    if(currTime - lastSend >= 5000) //send every five seconds
    {
        lastSend = currTime;
        espLogger.log(espLogger.ENCODER_L, (int) lastSend);
    }
    
    static int count = 0;
    if(buttonA.CheckButtonPress()) {
        count ++;
        espLogger.log(espLogger.PITCH, count);
    }

    if (timer.checkExpired(true)) {
        espLogger.update();
    }
}