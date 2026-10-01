"""LM5145 (LM25145-compatible) 20 V -> 5 V / 18 A buck: ripple, Type-III compensation,
small-signal loop check (nominal + component corners) and loss budget.
Equations from the TI LM25145/LM5145 datasheets.  Run:  uv run --with numpy python design_calcs.py
"""
import numpy as np
pi=np.pi
Vout=5.0; Vref=0.8; kFF=15; fsw=400e3; Iout=18.0
L=2.2e-6; DCR=2.5e-3
# output caps: 4x 220uF polymer (ESR 15m each) + 6x 47uF 10V X7R 1210 (~45% left at 5V -> ~21uF, ESR 3m each)
Cp=4*220e-6; ESRp=15e-3/4
Cc=6*21e-6;  ESRc=3e-3/6
for Vin in (16,20,24):
    D=Vout/Vin; dI=(Vin-Vout)*D/(L*fsw)
    print(f"Vin={Vin}: D={D:.3f} dI={dI:.2f}App Ipk={Iout+dI/2:.1f}A  ton={D/fsw*1e9:.0f}ns  Icin_rms={np.sqrt(D*(Iout**2*(1-D)+dI**2/12)):.2f}A")
Ctot=Cp+Cc
fo=1/(2*pi*np.sqrt(L*Ctot)); fesr=1/(2*pi*ESRp*Cp)
print(f"Ctot={Ctot*1e6:.0f}uF fo={fo:.0f}Hz f_esr(polymer)={fesr/1e3:.1f}kHz")
fc=40e3
Kmid=fc/fo/kFF
RFB1=23.2e3; RFB2=RFB1/(Vout/Vref-1)
RC1=Kmid*RFB1
wo=2*pi*fo
CC1=2/(wo*RC1); CC2=1/(pi*fsw*RC1); CC3=1/(wo*RFB1); RC2=1/(2*pi*fesr*CC3)
print(f"Kmid={Kmid:.3f} RFB2={RFB2:.0f} RC1={RC1:.0f} CC1={CC1*1e9:.2f}n CC2={CC2*1e12:.1f}p CC3={CC3*1e9:.2f}n RC2={RC2:.0f}")
def E96(x):
    s=np.array([100,102,105,107,110,113,115,118,121,124,127,130,133,137,140,143,147,150,154,158,162,165,169,174,178,182,187,191,196,200,205,210,215,221,226,232,237,243,249,255,261,267,274,280,287,294,301,309,316,324,332,340,348,357,365,374,383,392,402,412,422,432,442,453,464,475,487,499,511,523,536,549,562,576,590,604,619,634,649,665,681,698,715,732,750,768,787,806,825,845,866,887,909,931,953,976])
    e=10**np.floor(np.log10(x)); m=x/e*100; return s[np.argmin(abs(s-m))]*e/100
def E12(x):
    s=np.array([1.0,1.2,1.5,1.8,2.2,2.7,3.3,3.9,4.7,5.6,6.8,8.2]); e=10**np.floor(np.log10(x)); m=x/e; return s[np.argmin(abs(s-m))]*e
# chosen standard values
c=dict(RFB1=23.2e3,RFB2=4.42e3,RC1=E96(RC1),RC2=E96(RC2),CC1=E12(CC1),CC2=E12(CC2),CC3=E12(CC3))
print({k:f"{v:.4g}" for k,v in c.items()}, "Vout=",Vref*(1+c['RFB1']/c['RFB2']))
f=np.logspace(2,6,4000); s=2j*pi*f
def loop(Iload,Vin=20,cc=c):
    D_=Vout/Vin
    Rdamp=DCR+D_*5e-3+(1-D_)*2.8e-3
    Zp=ESRp+1/(s*Cp); Zc=ESRc+1/(s*Cc); Zo=1/(1/Zp+1/Zc)
    RL=Vout/Iload; Zl=1/(1/Zo+1/RL)
    H=Zl/(s*L+Rdamp+Zl)
    Zf=1/(1/(cc['RC1']+1/(s*cc['CC1']))+s*cc['CC2'])
    Zi=1/(1/cc['RFB1']+1/(cc['RC2']+1/(s*cc['CC3'])))
    T=kFF*H*Zf/Zi
    # 400kHz sampling ignored; add half-sw delay approx
    T=T*np.exp(-s*0.5/fsw*0.5)
    mag=20*np.log10(abs(T)); ph=np.unwrap(np.angle(T))*180/pi
    i=np.where(np.diff(np.sign(mag)))[0][-1]
    pm=180+ph[i]
    j=np.where(np.diff(np.sign(ph+180)))[0]
    gm=-mag[j[-1]] if len(j) else float('nan')
    return f[i],pm,gm
for Il in (0.5,5,18):
    for Vin in (16,20,24):
        fcx,pm,gm=loop(Il,Vin); print(f"I={Il:>4}A Vin={Vin}: fc={fcx/1e3:.1f}kHz PM={pm:.0f}deg GM={gm:.1f}dB")

print("--- corners (Vin=20, I=5A) ---")
for esr_each,cfrac,label in ((7e-3,1,'low ESR polymer'),(25e-3,1,'high ESR polymer'),(15e-3,0.6,'ceramics derated more'),(15e-3,1.5,'ceramics derated less')):
    ESRp=esr_each/4; Cc=6*21e-6*cfrac
    fcx,pm,gm=loop(5,20); print(f"{label}: fc={fcx/1e3:.1f}kHz PM={pm:.0f} GM={gm:.1f}dB")
ESRp=15e-3/4; Cc=6*21e-6
# Cp -20% tolerance
Cp=0.8*880e-6; fcx,pm,gm=loop(5,20); print(f"polymer -20%: fc={fcx/1e3:.1f}kHz PM={pm:.0f} GM={gm:.1f}dB"); Cp=880e-6
# losses @ Vin=20, 18A
Vin=20;D=0.25;dI=4.26
Rhs=3.7e-3*1.4; Rls=2.0e-3*1.4
irms2=Iout**2+dI**2/12
P=dict(HS_cond=D*irms2*Rhs, HS_sw=0.5*Vin*Iout*(6e-9+6e-9)*fsw, LS_cond=(1-D)*irms2*Rls,
       deadtime=0.8*fsw*Iout*2*14e-9, gate=7.5*fsw*(25e-9+50e-9), Qrr_Coss=Vin*fsw*(40e-9+25e-9),
       L_DCR=irms2*DCR, L_core=0.4, Cin_ESR=7.8**2*2e-3/6+7.8**2*0.0,  pcb=Iout**2*1.0e-3)
Iin=(Vout*Iout+sum(P.values()))/Vin
P['eFuse']=Iin**2*35e-3; P['ideal_diode_FET']=Iin**2*4e-3
tot=sum(P.values())
for k,v in P.items(): print(f"{k:>16}: {v:.2f} W")
print(f"total {tot:.2f} W  eff={90/(90+tot)*100:.1f}%  Iin={(90+tot)/20:.2f}A @20V")
