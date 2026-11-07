#include <xc.h>

#define _XTAL_FREQ 20000000

#pragma config FOSC = HS
#pragma config WDTE = OFF
#pragma config PWRTE = OFF
#pragma config BOREN = ON
#pragma config LVP = OFF
#pragma config CPD = OFF
#pragma config WRT = OFF
#pragma config CP = OFF

void UART_Init(void) {
    TRISCbits.TRISC6 = 0; // TX
    TRISCbits.TRISC7 = 1; // RX
    SPBRG = 129;          // 9600 baud @ 20MHz
    BRGH = 1;
    SYNC = 0;
    SPEN = 1;
    TXEN = 1;
    CREN = 1;
}

char UART_Receive(void) {
    // Xu ly loi tran bo dem OERR neu co truoc khi cho RCIF
    if(RCSTAbits.OERR) {
        RCSTAbits.CREN = 0;
        RCSTAbits.CREN = 1;
    }
    while(!PIR1bits.RCIF) {
        if(RCSTAbits.OERR) {
            RCSTAbits.CREN = 0;
            RCSTAbits.CREN = 1;
        }
    }
    return RCREG;
}

void Output_Init(void) {
    ADCON1 = 0x06;
    // RD0 (Relay mo cong), RD1 (Buzzer coi)
    TRISDbits.TRISD0 = 0;
    TRISDbits.TRISD1 = 0;
    PORTD = 0x00;
}

void main(void) {
    char data;
    Output_Init();
    UART_Init();

    while(1) {
        data = UART_Receive();

        if(data == 'F') {
            PORTDbits.RD0 = 0; // Ngat relay
            PORTDbits.RD1 = 0; // Tat coi
        }
        else if(data == '1') { // Mat khau trung khop
            PORTDbits.RD0 = 1; // Dong Relay RL1 -> MO CONG (Motor quay)
            PORTDbits.RD1 = 0; // Tat coi
        }
        else if(data == '0') { // Mat khau sai
            PORTDbits.RD0 = 0; // Dong cong (Relay ngat)
            PORTDbits.RD1 = 1; // Bat coi BUZ1 canh bao
            __delay_ms(1500);
            PORTDbits.RD1 = 0;
        }
    }
}
