# ESY Sunhome for Home Assistant

This is an initial version of a custom component for the ESY Sunhome battery, it is a work in progress and my first custom component.

For those who are looking to purchase/install a sunhome battery, get $50 off using my code: AU1587 when you register and set up the ESY sunhome app. If like me, you're switching to Amber for wholesale rates, you can use code QVLA4DT4 to get $120 off.

![Example Screenshot](/docs/screenshot.png)

Special thanks to airzone for documenting so much of the inner workings over at: [@airzone-sama](https://github.com/airzone-sama/esy_sunhome) 

## Installation

The simplest method is using 'HACS':

- Go to HACS / Integrations
- Click the 3 dots in the top right
- Select "Custom repositories"
- Add the repository URL - https://github.com/branko-lazarevic/esysunhome
- Select category Integration
- Click ADD
- Now from HACS / Integrations you can find ESY Sunhome and click Download
- Restart Home Assistant

Now you can add the integration using the ADD INTERGATION button in Settings / Devices & services, search for ESY Sunhome.
It will ask you for your username and password that you use in the ESY mobile app and it will prompt you for the inverter ID, if you don't know it and only have one in your account then just click next and it will default to the first one on your account.

## Sensors, Dashboards & Automation

As mentioned previously, this is a work in progress through trial and error to determine what works best for me but if you'd like to follow my progress, i'll keep the github pages updated here: [ESY Sunhome Battery Home Assistant Integration](https://branko-lazarevic.github.io/esysunhome)