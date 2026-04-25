#include <Mouse.h>

byte AInput = 5;
byte BInput = 6;
 
byte lastState = 0;
byte steps = 0;
int  cw = 0;
byte AState = 0;
byte BState = 0;
byte State = 0;
 
void setup() {
  Serial.begin(9600);
  pinMode(AInput, INPUT);
  pinMode(BInput, INPUT);
}
 
void loop() {
  // read the input pin:
  AState = digitalRead(AInput);
  BState = digitalRead(BInput) << 1;
  State = AState | BState;
 
  if (lastState != State){
    switch (State) {
      case 0:
        if (lastState == 2){
          steps++;
          cw = 1;
        }
        else if(lastState == 1){
          steps--;
          cw = -1;
        }
        break;
      case 1:
        if (lastState == 0){
          steps++;
          cw = 1;
        }
        else if(lastState == 3){
          steps--;
          cw = -1;
        }
        break;
      case 2:
        if (lastState == 3){
          steps++;
          cw = 1;
        }
        else if(lastState == 0){
          steps--;
          cw = -1;
        }
        break;
      case 3:
        if (lastState == 1){
          steps++;
          cw = 1;
        }
        else if(lastState == 2){
          steps--;
          cw = -1;
        }
        break;
    }
   {
      Mouse.begin();
      Mouse.move(0,0, steps);
    
    } 
  }
 
  lastState = State;
  Serial.print(State);
  Serial.print("\t");
  Serial.print(cw);
  Serial.print("\t");
  Serial.println(steps);
  delay(1);
}
