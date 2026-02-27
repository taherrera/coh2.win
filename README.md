This is a copy of the website coh2.win, now hosted in coh2.win.sltech.cl



The idea of adding the website to github is so that everyone who enjoys the game can collaborate, make or propose changes, clean up the website, etc.



As you can notice there are some issues right now with the website, mainly, some images do not show up, so if you can help correcting this, you are welcome.



To change image url:

find . -type f -name "\*.html" -exec sed -i 's|sites/default/files/styles/doctrine/public/2021-12/Icons\_portraits\_unit\_us\_assault\_commander\_s\_portrait5778.html|sites/default/files/game\_icons/Icons\_commander\_portrait\_us\_forces\_commander\_02\_large.png|g' {} +

