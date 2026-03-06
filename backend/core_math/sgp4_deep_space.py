"""Deep-space SGP4 support for LinkSpot's in-repo propagator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .time import datetime_to_julian_parts, ensure_utc, gmst_radians
from .types import TemeState, TleRecord

WGS72_MU_KM3_S2 = 398600.8
WGS72_RADIUS_EARTH_KM = 6378.135
WGS72_XKE = 60.0 / math.sqrt(
    (WGS72_RADIUS_EARTH_KM * WGS72_RADIUS_EARTH_KM * WGS72_RADIUS_EARTH_KM)
    / WGS72_MU_KM3_S2
)
WGS72_J2 = 0.001082616
WGS72_J3 = -0.00000253881
WGS72_J4 = -0.00000165597
WGS72_J3OJ2 = WGS72_J3 / WGS72_J2

TWOPI = 2.0 * math.pi
X2O3 = 2.0 / 3.0
TEMP4 = 1.5e-12
QOMS2T = ((120.0 - 78.0) / WGS72_RADIUS_EARTH_KM) ** 4
S4_BASE = 78.0 / WGS72_RADIUS_EARTH_KM + 1.0
VKM_PER_SEC = WGS72_RADIUS_EARTH_KM * WGS72_XKE / 60.0


def _positive_mod(value: float, modulus: float = TWOPI) -> float:
    wrapped = math.fmod(value, modulus)
    if wrapped < 0.0:
        wrapped += modulus
    return wrapped


def _deep_space_epoch_days(epoch_utc: datetime) -> float:
    jd, frac = datetime_to_julian_parts(ensure_utc(epoch_utc))
    return jd + frac - 2433281.5


def _dpper(
    terms: dict[str, float],
    t_minutes: float,
    inclo: float,
    init: str,
    ep: float,
    inclp: float,
    nodep: float,
    argpp: float,
    mp: float,
    opsmode: str = "i",
) -> tuple[float, float, float, float, float]:
    zns = 1.19459e-5
    zes = 0.01675
    znl = 1.5835218e-4
    zel = 0.05490

    zm = terms["zmos"] + zns * t_minutes
    if init == "y":
        zm = terms["zmos"]
    zf = zm + 2.0 * zes * math.sin(zm)
    sinzf = math.sin(zf)
    f2 = 0.5 * sinzf * sinzf - 0.25
    f3 = -0.5 * sinzf * math.cos(zf)
    ses = terms["se2"] * f2 + terms["se3"] * f3
    sis = terms["si2"] * f2 + terms["si3"] * f3
    sls = terms["sl2"] * f2 + terms["sl3"] * f3 + terms["sl4"] * sinzf
    sghs = terms["sgh2"] * f2 + terms["sgh3"] * f3 + terms["sgh4"] * sinzf
    shs = terms["sh2"] * f2 + terms["sh3"] * f3

    zm = terms["zmol"] + znl * t_minutes
    if init == "y":
        zm = terms["zmol"]
    zf = zm + 2.0 * zel * math.sin(zm)
    sinzf = math.sin(zf)
    f2 = 0.5 * sinzf * sinzf - 0.25
    f3 = -0.5 * sinzf * math.cos(zf)
    sel = terms["ee2"] * f2 + terms["e3"] * f3
    sil = terms["xi2"] * f2 + terms["xi3"] * f3
    sll = terms["xl2"] * f2 + terms["xl3"] * f3 + terms["xl4"] * sinzf
    sghl = terms["xgh2"] * f2 + terms["xgh3"] * f3 + terms["xgh4"] * sinzf
    shll = terms["xh2"] * f2 + terms["xh3"] * f3

    pe = ses + sel
    pinc = sis + sil
    pl = sls + sll
    pgh = sghs + sghl
    ph = shs + shll

    if init == "n":
        pe -= terms["peo"]
        pinc -= terms["pinco"]
        pl -= terms["plo"]
        pgh -= terms["pgho"]
        ph -= terms["pho"]

        inclp = inclp + pinc
        ep = ep + pe
        sinip = math.sin(inclp)
        cosip = math.cos(inclp)

        if inclp >= 0.2:
            ph = ph / sinip
            pgh = pgh - cosip * ph
            argpp = argpp + pgh
            nodep = nodep + ph
            mp = mp + pl
        else:
            sinop = math.sin(nodep)
            cosop = math.cos(nodep)
            alfdp = sinip * sinop
            betdp = sinip * cosop
            dalf = ph * cosop + pinc * cosip * sinop
            dbet = -ph * sinop + pinc * cosip * cosop
            alfdp = alfdp + dalf
            betdp = betdp + dbet
            nodep = math.fmod(nodep, TWOPI)
            if nodep < 0.0 and opsmode == "a":
                nodep += TWOPI
            xls = mp + argpp + cosip * nodep
            dls = pl + pgh - pinc * nodep * sinip
            xls = xls + dls
            xnoh = nodep
            nodep = math.atan2(alfdp, betdp)
            if nodep < 0.0 and opsmode == "a":
                nodep += TWOPI
            if abs(xnoh - nodep) > math.pi:
                if nodep < xnoh:
                    nodep += TWOPI
                else:
                    nodep -= TWOPI
            mp = mp + pl
            argpp = xls - mp - cosip * nodep

    _ = inclo
    return ep, inclp, nodep, argpp, mp


def _dscom(
    epoch: float,
    ep: float,
    argpp: float,
    tc: float,
    inclp: float,
    nodep: float,
    np: float,
) -> dict[str, float]:
    zes = 0.01675
    zel = 0.05490
    c1ss = 2.9864797e-6
    c1l = 4.7968065e-7
    zsinis = 0.39785416
    zcosis = 0.91744867
    zcosgs = 0.1945905
    zsings = -0.98088458

    nm = np
    em = ep
    snodm = math.sin(nodep)
    cnodm = math.cos(nodep)
    sinomm = math.sin(argpp)
    cosomm = math.cos(argpp)
    sinim = math.sin(inclp)
    cosim = math.cos(inclp)
    emsq = em * em
    betasq = 1.0 - emsq
    rtemsq = math.sqrt(betasq)

    peo = 0.0
    pinco = 0.0
    plo = 0.0
    pgho = 0.0
    pho = 0.0
    day = epoch + 18261.5 + tc / 1440.0
    xnodce = _positive_mod(4.5236020 - 9.2422029e-4 * day)
    stem = math.sin(xnodce)
    ctem = math.cos(xnodce)
    zcosil = 0.91375164 - 0.03568096 * ctem
    zsinil = math.sqrt(1.0 - zcosil * zcosil)
    zsinhl = 0.089683511 * stem / zsinil
    zcoshl = math.sqrt(1.0 - zsinhl * zsinhl)
    gam = 5.8351514 + 0.0019443680 * day
    zx = 0.39785416 * stem / zsinil
    zy = zcoshl * ctem + 0.91744867 * zsinhl * stem
    zx = math.atan2(zx, zy)
    zx = gam + zx - xnodce
    zcosgl = math.cos(zx)
    zsingl = math.sin(zx)

    zcosg = zcosgs
    zsing = zsings
    zcosi = zcosis
    zsini = zsinis
    zcosh = cnodm
    zsinh = snodm
    cc = c1ss
    xnoi = 1.0 / nm

    solar_lunar: dict[str, float] = {}
    for iteration in (1, 2):
        a1 = zcosg * zcosh + zsing * zcosi * zsinh
        a3 = -zsing * zcosh + zcosg * zcosi * zsinh
        a7 = -zcosg * zsinh + zsing * zcosi * zcosh
        a8 = zsing * zsini
        a9 = zsing * zsinh + zcosg * zcosi * zcosh
        a10 = zcosg * zsini
        a2 = cosim * a7 + sinim * a8
        a4 = cosim * a9 + sinim * a10
        a5 = -sinim * a7 + cosim * a8
        a6 = -sinim * a9 + cosim * a10

        x1 = a1 * cosomm + a2 * sinomm
        x2 = a3 * cosomm + a4 * sinomm
        x3 = -a1 * sinomm + a2 * cosomm
        x4 = -a3 * sinomm + a4 * cosomm
        x5 = a5 * sinomm
        x6 = a6 * sinomm
        x7 = a5 * cosomm
        x8 = a6 * cosomm

        z31 = 12.0 * x1 * x1 - 3.0 * x3 * x3
        z32 = 24.0 * x1 * x2 - 6.0 * x3 * x4
        z33 = 12.0 * x2 * x2 - 3.0 * x4 * x4
        z1 = 3.0 * (a1 * a1 + a2 * a2) + z31 * emsq
        z2 = 6.0 * (a1 * a3 + a2 * a4) + z32 * emsq
        z3 = 3.0 * (a3 * a3 + a4 * a4) + z33 * emsq
        z11 = -6.0 * a1 * a5 + emsq * (-24.0 * x1 * x7 - 6.0 * x3 * x5)
        z12 = -6.0 * (a1 * a6 + a3 * a5) + emsq * (
            -24.0 * (x2 * x7 + x1 * x8) - 6.0 * (x3 * x6 + x4 * x5)
        )
        z13 = -6.0 * a3 * a6 + emsq * (-24.0 * x2 * x8 - 6.0 * x4 * x6)
        z21 = 6.0 * a2 * a5 + emsq * (24.0 * x1 * x5 - 6.0 * x3 * x7)
        z22 = 6.0 * (a4 * a5 + a2 * a6) + emsq * (
            24.0 * (x2 * x5 + x1 * x6) - 6.0 * (x4 * x7 + x3 * x8)
        )
        z23 = 6.0 * a4 * a6 + emsq * (24.0 * x2 * x6 - 6.0 * x4 * x8)
        z1 = z1 + z1 + betasq * z31
        z2 = z2 + z2 + betasq * z32
        z3 = z3 + z3 + betasq * z33
        s3 = cc * xnoi
        s2 = -0.5 * s3 / rtemsq
        s4 = s3 * rtemsq
        s1 = -15.0 * em * s4
        s5 = x1 * x3 + x2 * x4
        s6 = x2 * x3 + x1 * x4
        s7 = x2 * x4 - x1 * x3

        if iteration == 1:
            solar_lunar.update(
                {
                    "ss1": s1,
                    "ss2": s2,
                    "ss3": s3,
                    "ss4": s4,
                    "ss5": s5,
                    "ss6": s6,
                    "ss7": s7,
                    "sz1": z1,
                    "sz2": z2,
                    "sz3": z3,
                    "sz11": z11,
                    "sz12": z12,
                    "sz13": z13,
                    "sz21": z21,
                    "sz22": z22,
                    "sz23": z23,
                    "sz31": z31,
                    "sz32": z32,
                    "sz33": z33,
                }
            )
            zcosg = zcosgl
            zsing = zsingl
            zcosi = zcosil
            zsini = zsinil
            zcosh = zcoshl * cnodm + zsinhl * snodm
            zsinh = snodm * zcoshl - cnodm * zsinhl
            cc = c1l
        else:
            solar_lunar.update(
                {
                    "s1": s1,
                    "s2": s2,
                    "s3": s3,
                    "s4": s4,
                    "s5": s5,
                    "s6": s6,
                    "s7": s7,
                    "z1": z1,
                    "z2": z2,
                    "z3": z3,
                    "z11": z11,
                    "z12": z12,
                    "z13": z13,
                    "z21": z21,
                    "z22": z22,
                    "z23": z23,
                    "z31": z31,
                    "z32": z32,
                    "z33": z33,
                }
            )

    zmol = _positive_mod(4.7199672 + 0.22997150 * day - gam)
    zmos = _positive_mod(6.2565837 + 0.017201977 * day)

    result = {
        "snodm": snodm,
        "cnodm": cnodm,
        "sinim": sinim,
        "cosim": cosim,
        "sinomm": sinomm,
        "cosomm": cosomm,
        "day": day,
        "e3": 2.0 * solar_lunar["s1"] * solar_lunar["s7"],
        "ee2": 2.0 * solar_lunar["s1"] * solar_lunar["s6"],
        "em": em,
        "emsq": emsq,
        "gam": gam,
        "peo": peo,
        "pgho": pgho,
        "pho": pho,
        "pinco": pinco,
        "plo": plo,
        "rtemsq": rtemsq,
        "se2": 2.0 * solar_lunar["ss1"] * solar_lunar["ss6"],
        "se3": 2.0 * solar_lunar["ss1"] * solar_lunar["ss7"],
        "sgh2": 2.0 * solar_lunar["ss4"] * solar_lunar["sz32"],
        "sgh3": 2.0 * solar_lunar["ss4"] * (solar_lunar["sz33"] - solar_lunar["sz31"]),
        "sgh4": -18.0 * solar_lunar["ss4"] * zes,
        "sh2": -2.0 * solar_lunar["ss2"] * solar_lunar["sz22"],
        "sh3": -2.0 * solar_lunar["ss2"] * (solar_lunar["sz23"] - solar_lunar["sz21"]),
        "si2": 2.0 * solar_lunar["ss2"] * solar_lunar["sz12"],
        "si3": 2.0 * solar_lunar["ss2"] * (solar_lunar["sz13"] - solar_lunar["sz11"]),
        "sl2": -2.0 * solar_lunar["ss3"] * solar_lunar["sz2"],
        "sl3": -2.0 * solar_lunar["ss3"] * (solar_lunar["sz3"] - solar_lunar["sz1"]),
        "sl4": -2.0 * solar_lunar["ss3"] * (-21.0 - 9.0 * emsq) * zes,
        "nm": nm,
        "xh2": -2.0 * solar_lunar["s2"] * solar_lunar["z22"],
        "xh3": -2.0 * solar_lunar["s2"] * (solar_lunar["z23"] - solar_lunar["z21"]),
        "xi2": 2.0 * solar_lunar["s2"] * solar_lunar["z12"],
        "xi3": 2.0 * solar_lunar["s2"] * (solar_lunar["z13"] - solar_lunar["z11"]),
        "xl2": -2.0 * solar_lunar["s3"] * solar_lunar["z2"],
        "xl3": -2.0 * solar_lunar["s3"] * (solar_lunar["z3"] - solar_lunar["z1"]),
        "xl4": -2.0 * solar_lunar["s3"] * (-21.0 - 9.0 * emsq) * zel,
        "xgh2": 2.0 * solar_lunar["s4"] * solar_lunar["z32"],
        "xgh3": 2.0 * solar_lunar["s4"] * (solar_lunar["z33"] - solar_lunar["z31"]),
        "xgh4": -18.0 * solar_lunar["s4"] * zel,
        "zmol": zmol,
        "zmos": zmos,
        **solar_lunar,
    }
    return result


def _dsinit(
    cosim: float,
    emsq: float,
    argpo: float,
    dscom: dict[str, float],
    mo: float,
    mdot: float,
    no_unkozai: float,
    nodeo: float,
    nodedot: float,
    xpidot: float,
    ecco: float,
    eccsq: float,
    inclm: float,
    gsto: float,
) -> dict[str, float | int]:
    q22 = 1.7891679e-6
    q31 = 2.1460748e-6
    q33 = 2.2123015e-7
    root22 = 1.7891679e-6
    root44 = 7.3636953e-9
    root54 = 2.1765803e-9
    rptim = 4.37526908801129966e-3
    root32 = 3.7393792e-7
    root52 = 1.1428639e-7
    znl = 1.5835218e-4
    zns = 1.19459e-5

    irez = 0
    if 0.0034906585 < dscom["nm"] < 0.0052359877:
        irez = 1
    if 8.26e-3 <= dscom["nm"] <= 9.24e-3 and dscom["em"] >= 0.5:
        irez = 2

    ses = dscom["ss1"] * zns * dscom["ss5"]
    sis = dscom["ss2"] * zns * (dscom["sz11"] + dscom["sz13"])
    sls = -zns * dscom["ss3"] * (dscom["sz1"] + dscom["sz3"] - 14.0 - 6.0 * emsq)
    sghs = dscom["ss4"] * zns * (dscom["sz31"] + dscom["sz33"] - 6.0)
    shs = -zns * dscom["ss2"] * (dscom["sz21"] + dscom["sz23"])
    if inclm < 5.2359877e-2 or inclm > math.pi - 5.2359877e-2:
        shs = 0.0
    if dscom["sinim"] != 0.0:
        shs = shs / dscom["sinim"]
    sgs = sghs - cosim * shs

    dedt = ses + dscom["s1"] * znl * dscom["s5"]
    didt = sis + dscom["s2"] * znl * (dscom["z11"] + dscom["z13"])
    dmdt = sls - znl * dscom["s3"] * (dscom["z1"] + dscom["z3"] - 14.0 - 6.0 * emsq)
    sghl = dscom["s4"] * znl * (dscom["z31"] + dscom["z33"] - 6.0)
    shll = -znl * dscom["s2"] * (dscom["z21"] + dscom["z23"])
    if inclm < 5.2359877e-2 or inclm > math.pi - 5.2359877e-2:
        shll = 0.0
    domdt = sgs + sghl
    dnodt = shs
    if dscom["sinim"] != 0.0:
        domdt = domdt - cosim / dscom["sinim"] * shll
        dnodt = dnodt + shll / dscom["sinim"]

    dndt = 0.0
    theta = _positive_mod(gsto)
    em = dscom["em"]
    nm = dscom["nm"]
    argpm = 0.0
    nodem = 0.0
    mm = 0.0
    atime = 0.0
    d2201 = d2211 = d3210 = d3222 = 0.0
    d4410 = d4422 = d5220 = d5232 = d5421 = d5433 = 0.0
    del1 = del2 = del3 = 0.0
    xfact = 0.0
    xlamo = 0.0
    xli = 0.0
    xni = 0.0

    em = em + dedt * 0.0
    inclm = inclm + didt * 0.0
    argpm = argpm + domdt * 0.0
    nodem = nodem + dnodt * 0.0
    mm = mm + dmdt * 0.0

    if irez != 0:
        aonv = math.pow(nm / WGS72_XKE, X2O3)

        if irez == 2:
            cosisq = cosim * cosim
            emo = em
            em = ecco
            emsqo = emsq
            emsq = eccsq
            eoc = em * emsq
            g201 = -0.306 - (em - 0.64) * 0.440

            if em <= 0.65:
                g211 = 3.616 - 13.2470 * em + 16.2900 * emsq
                g310 = -19.302 + 117.3900 * em - 228.4190 * emsq + 156.5910 * eoc
                g322 = -18.9068 + 109.7927 * em - 214.6334 * emsq + 146.5816 * eoc
                g410 = -41.122 + 242.6940 * em - 471.0940 * emsq + 313.9530 * eoc
                g422 = -146.407 + 841.8800 * em - 1629.014 * emsq + 1083.4350 * eoc
                g520 = -532.114 + 3017.977 * em - 5740.032 * emsq + 3708.2760 * eoc
            else:
                g211 = -72.099 + 331.819 * em - 508.738 * emsq + 266.724 * eoc
                g310 = -346.844 + 1582.851 * em - 2415.925 * emsq + 1246.113 * eoc
                g322 = -342.585 + 1554.908 * em - 2366.899 * emsq + 1215.972 * eoc
                g410 = -1052.797 + 4758.686 * em - 7193.992 * emsq + 3651.957 * eoc
                g422 = -3581.690 + 16178.110 * em - 24462.770 * emsq + 12422.520 * eoc
                if em > 0.715:
                    g520 = -5149.66 + 29936.92 * em - 54087.36 * emsq + 31324.56 * eoc
                else:
                    g520 = 1464.74 - 4664.75 * em + 3763.64 * emsq

            if em < 0.7:
                g533 = -919.22770 + 4988.6100 * em - 9064.7700 * emsq + 5542.21 * eoc
                g521 = -822.71072 + 4568.6173 * em - 8491.4146 * emsq + 5337.524 * eoc
                g532 = -853.66600 + 4690.2500 * em - 8624.7700 * emsq + 5341.4 * eoc
            else:
                g533 = -37995.780 + 161616.52 * em - 229838.20 * emsq + 109377.94 * eoc
                g521 = -51752.104 + 218913.95 * em - 309468.16 * emsq + 146349.42 * eoc
                g532 = -40023.880 + 170470.89 * em - 242699.48 * emsq + 115605.82 * eoc

            sini2 = dscom["sinim"] * dscom["sinim"]
            f220 = 0.75 * (1.0 + 2.0 * cosim + cosisq)
            f221 = 1.5 * sini2
            f321 = 1.875 * dscom["sinim"] * (1.0 - 2.0 * cosim - 3.0 * cosisq)
            f322 = -1.875 * dscom["sinim"] * (1.0 + 2.0 * cosim - 3.0 * cosisq)
            f441 = 35.0 * sini2 * f220
            f442 = 39.3750 * sini2 * sini2
            f522 = 9.84375 * dscom["sinim"] * (
                sini2 * (1.0 - 2.0 * cosim - 5.0 * cosisq)
                + 0.33333333 * (-2.0 + 4.0 * cosim + 6.0 * cosisq)
            )
            f523 = dscom["sinim"] * (
                4.92187512 * sini2 * (-2.0 - 4.0 * cosim + 10.0 * cosisq)
                + 6.56250012 * (1.0 + 2.0 * cosim - 3.0 * cosisq)
            )
            f542 = 29.53125 * dscom["sinim"] * (
                2.0 - 8.0 * cosim + cosisq * (-12.0 + 8.0 * cosim + 10.0 * cosisq)
            )
            f543 = 29.53125 * dscom["sinim"] * (
                -2.0 - 8.0 * cosim + cosisq * (12.0 + 8.0 * cosim - 10.0 * cosisq)
            )
            xno2 = nm * nm
            ainv2 = aonv * aonv
            temp1 = 3.0 * xno2 * ainv2
            temp = temp1 * root22
            d2201 = temp * f220 * g201
            d2211 = temp * f221 * g211
            temp1 = temp1 * aonv
            temp = temp1 * root32
            d3210 = temp * f321 * g310
            d3222 = temp * f322 * g322
            temp1 = temp1 * aonv
            temp = 2.0 * temp1 * root44
            d4410 = temp * f441 * g410
            d4422 = temp * f442 * g422
            temp1 = temp1 * aonv
            temp = temp1 * root52
            d5220 = temp * f522 * g520
            d5232 = temp * f523 * g532
            temp = 2.0 * temp1 * root54
            d5421 = temp * f542 * g521
            d5433 = temp * f543 * g533
            xlamo = _positive_mod(mo + nodeo + nodeo - theta - theta)
            xfact = mdot + dmdt + 2.0 * (nodedot + dnodt - rptim) - no_unkozai
            em = emo
            emsq = emsqo

        if irez == 1:
            g200 = 1.0 + emsq * (-2.5 + 0.8125 * emsq)
            g310 = 1.0 + 2.0 * emsq
            g300 = 1.0 + emsq * (-6.0 + 6.60937 * emsq)
            f220 = 0.75 * (1.0 + cosim) * (1.0 + cosim)
            f311 = 0.9375 * dscom["sinim"] * dscom["sinim"] * (1.0 + 3.0 * cosim) - 0.75 * (1.0 + cosim)
            f330 = 1.875 * (1.0 + cosim) * (1.0 + cosim) * (1.0 + cosim)
            del1 = 3.0 * nm * nm * aonv * aonv
            del2 = 2.0 * del1 * f220 * g200 * q22
            del3 = 3.0 * del1 * f330 * g300 * q33 * aonv
            del1 = del1 * f311 * g310 * q31 * aonv
            xlamo = _positive_mod(mo + nodeo + argpo - theta)
            xfact = mdot + xpidot - rptim + dmdt + domdt + dnodt - no_unkozai

        xli = xlamo
        xni = no_unkozai
        atime = 0.0
        nm = no_unkozai + dndt

    return {
        "gsto": gsto,
        "irez": irez,
        "atime": atime,
        "d2201": d2201,
        "d2211": d2211,
        "d3210": d3210,
        "d3222": d3222,
        "d4410": d4410,
        "d4422": d4422,
        "d5220": d5220,
        "d5232": d5232,
        "d5421": d5421,
        "d5433": d5433,
        "dedt": dedt,
        "didt": didt,
        "dmdt": dmdt,
        "dndt": dndt,
        "dnodt": dnodt,
        "domdt": domdt,
        "del1": del1,
        "del2": del2,
        "del3": del3,
        "xfact": xfact,
        "xlamo": xlamo,
        "xli": xli,
        "xni": xni,
    }


def _dspace(
    deep_terms: dict[str, float | int],
    t_minutes: float,
    tc_minutes: float,
    em: float,
    argpm: float,
    inclm: float,
    xli: float,
    mm: float,
    xni: float,
    nodem: float,
    no_unkozai: float,
    argpo: float,
    argpdot: float,
) -> dict[str, float]:
    fasx2 = 0.13130908
    fasx4 = 2.8843198
    fasx6 = 0.37448087
    g22 = 5.7686396
    g32 = 0.95240898
    g44 = 1.8014998
    g52 = 1.0508330
    g54 = 4.4108898
    rptim = 4.37526908801129966e-3
    stepp = 720.0
    stepn = -720.0
    step2 = 259200.0

    dndt = 0.0
    theta = _positive_mod(float(deep_terms["gsto"]) + tc_minutes * rptim)
    em = em + float(deep_terms["dedt"]) * t_minutes
    inclm = inclm + float(deep_terms["didt"]) * t_minutes
    argpm = argpm + float(deep_terms["domdt"]) * t_minutes
    nodem = nodem + float(deep_terms["dnodt"]) * t_minutes
    mm = mm + float(deep_terms["dmdt"]) * t_minutes

    atime = float(deep_terms["atime"])
    irez = int(deep_terms["irez"])
    ft = 0.0
    if irez != 0:
        if atime == 0.0 or (t_minutes * atime <= 0.0) or (abs(t_minutes) < abs(atime)):
            atime = 0.0
            xni = no_unkozai
            xli = float(deep_terms["xlamo"])

        delt = stepp if t_minutes > 0.0 else stepn
        while True:
            if irez != 2:
                xndt = float(deep_terms["del1"]) * math.sin(xli - fasx2) + float(deep_terms["del2"]) * math.sin(
                    2.0 * (xli - fasx4)
                ) + float(deep_terms["del3"]) * math.sin(3.0 * (xli - fasx6))
                xldot = xni + float(deep_terms["xfact"])
                xnddt = (
                    float(deep_terms["del1"]) * math.cos(xli - fasx2)
                    + 2.0 * float(deep_terms["del2"]) * math.cos(2.0 * (xli - fasx4))
                    + 3.0 * float(deep_terms["del3"]) * math.cos(3.0 * (xli - fasx6))
                ) * xldot
            else:
                xomi = argpo + argpdot * atime
                x2omi = xomi + xomi
                x2li = xli + xli
                xndt = (
                    float(deep_terms["d2201"]) * math.sin(x2omi + xli - g22)
                    + float(deep_terms["d2211"]) * math.sin(xli - g22)
                    + float(deep_terms["d3210"]) * math.sin(xomi + xli - g32)
                    + float(deep_terms["d3222"]) * math.sin(-xomi + xli - g32)
                    + float(deep_terms["d4410"]) * math.sin(x2omi + x2li - g44)
                    + float(deep_terms["d4422"]) * math.sin(x2li - g44)
                    + float(deep_terms["d5220"]) * math.sin(xomi + xli - g52)
                    + float(deep_terms["d5232"]) * math.sin(-xomi + xli - g52)
                    + float(deep_terms["d5421"]) * math.sin(xomi + x2li - g54)
                    + float(deep_terms["d5433"]) * math.sin(-xomi + x2li - g54)
                )
                xldot = xni + float(deep_terms["xfact"])
                xnddt = (
                    float(deep_terms["d2201"]) * math.cos(x2omi + xli - g22)
                    + float(deep_terms["d2211"]) * math.cos(xli - g22)
                    + float(deep_terms["d3210"]) * math.cos(xomi + xli - g32)
                    + float(deep_terms["d3222"]) * math.cos(-xomi + xli - g32)
                    + float(deep_terms["d5220"]) * math.cos(xomi + xli - g52)
                    + float(deep_terms["d5232"]) * math.cos(-xomi + xli - g52)
                    + 2.0
                    * (
                        float(deep_terms["d4410"]) * math.cos(x2omi + x2li - g44)
                        + float(deep_terms["d4422"]) * math.cos(x2li - g44)
                        + float(deep_terms["d5421"]) * math.cos(xomi + x2li - g54)
                        + float(deep_terms["d5433"]) * math.cos(-xomi + x2li - g54)
                    )
                ) * xldot

            if abs(t_minutes - atime) >= stepp:
                ft = 0.0
            else:
                ft = t_minutes - atime
                break

            xli = xli + xldot * delt + xndt * step2
            xni = xni + xndt * delt + xnddt * step2
            atime = atime + delt

        nm = xni + xndt * ft + xnddt * ft * ft * 0.5
        xl = xli + xldot * ft + xndt * ft * ft * 0.5
        if irez != 1:
            mm = xl - 2.0 * nodem + 2.0 * theta
        else:
            mm = xl - nodem - argpm + theta
        dndt = nm - no_unkozai
        nm = no_unkozai + dndt
    else:
        nm = no_unkozai

    return {
        "atime": atime,
        "em": em,
        "argpm": argpm,
        "inclm": inclm,
        "xli": xli,
        "mm": mm,
        "xni": xni,
        "nodem": nodem,
        "dndt": dndt,
        "nm": nm,
    }


@dataclass
class DeepSpaceSgp4Propagator:
    """Deep-space SGP4 propagator using in-repo resonance and periodic terms."""

    record: TleRecord
    ecco: float
    inclo: float
    nodeo: float
    argpo: float
    mo: float
    bstar: float
    no_unkozai: float
    con41: float
    x1mth2: float
    x7thm1: float
    cc1: float
    cc4: float
    cc5: float
    mdot: float
    argpdot: float
    nodedot: float
    omgcof: float
    xmcof: float
    nodecf: float
    t2cof: float
    xlcof: float
    aycof: float
    delmo: float
    sinmao: float
    deep_periodics: dict[str, float]
    deep_resonance: dict[str, float | int]

    @classmethod
    def from_tle(cls, record: TleRecord) -> DeepSpaceSgp4Propagator:
        no_kozai = float(record.mean_motion_rev_per_day) * TWOPI / 1440.0
        ecco = float(record.eccentricity)
        inclo = math.radians(record.inclination_deg)
        nodeo = math.radians(record.raan_deg)
        argpo = math.radians(record.argument_of_perigee_deg)
        mo = math.radians(record.mean_anomaly_deg)
        bstar = float(record.bstar)

        eccsq = ecco * ecco
        omeosq = 1.0 - eccsq
        rteosq = math.sqrt(omeosq)
        cosio = math.cos(inclo)
        cosio2 = cosio * cosio

        ak = math.pow(WGS72_XKE / no_kozai, X2O3)
        d1 = 0.75 * WGS72_J2 * (3.0 * cosio2 - 1.0) / (rteosq * omeosq)
        del1 = d1 / (ak * ak)
        adel = ak * (
            1.0 - del1 * del1 - del1 * (1.0 / 3.0 + 134.0 * del1 * del1 / 81.0)
        )
        del0 = d1 / (adel * adel)
        no_unkozai = no_kozai / (1.0 + del0)

        ao = math.pow(WGS72_XKE / no_unkozai, X2O3)
        sinio = math.sin(inclo)
        po = ao * omeosq
        con42 = 1.0 - 5.0 * cosio2
        con41 = -con42 - cosio2 - cosio2
        posq = po * po
        rp = ao * (1.0 - ecco)

        isimp = 1
        sfour = S4_BASE
        qzms24 = QOMS2T
        perigee_km = (rp - 1.0) * WGS72_RADIUS_EARTH_KM
        if perigee_km < 156.0:
            sfour = perigee_km - 78.0
            if perigee_km < 98.0:
                sfour = 20.0
            qzms24 = ((120.0 - sfour) / WGS72_RADIUS_EARTH_KM) ** 4
            sfour = sfour / WGS72_RADIUS_EARTH_KM + 1.0

        pinvsq = 1.0 / posq
        tsi = 1.0 / (ao - sfour)
        eta = ao * ecco * tsi
        etasq = eta * eta
        eeta = ecco * eta
        psisq = abs(1.0 - etasq)
        coef = qzms24 * math.pow(tsi, 4.0)
        coef1 = coef / math.pow(psisq, 3.5)
        cc2 = coef1 * no_unkozai * (
            ao * (1.0 + 1.5 * etasq + eeta * (4.0 + etasq))
            + 0.375
            * WGS72_J2
            * tsi
            / psisq
            * con41
            * (8.0 + 3.0 * etasq * (8.0 + etasq))
        )
        cc1 = bstar * cc2
        cc3 = 0.0
        if ecco > 1.0e-4:
            cc3 = -2.0 * coef * tsi * WGS72_J3OJ2 * no_unkozai * sinio / ecco
        x1mth2 = 1.0 - cosio2
        cc4 = 2.0 * no_unkozai * coef1 * ao * omeosq * (
            eta * (2.0 + 0.5 * etasq)
            + ecco * (0.5 + 2.0 * etasq)
            - WGS72_J2
            * tsi
            / (ao * psisq)
            * (
                -3.0
                * con41
                * (1.0 - 2.0 * eeta + etasq * (1.5 - 0.5 * eeta))
                + 0.75
                * x1mth2
                * (2.0 * etasq - eeta * (1.0 + etasq))
                * math.cos(2.0 * argpo)
            )
        )
        cc5 = 2.0 * coef1 * ao * omeosq * (
            1.0 + 2.75 * (etasq + eeta) + eeta * etasq
        )
        cosio4 = cosio2 * cosio2
        temp1 = 1.5 * WGS72_J2 * pinvsq * no_unkozai
        temp2 = 0.5 * temp1 * WGS72_J2 * pinvsq
        temp3 = -0.46875 * WGS72_J4 * pinvsq * pinvsq * no_unkozai
        mdot = no_unkozai + 0.5 * temp1 * rteosq * con41 + 0.0625 * temp2 * rteosq * (
            13.0 - 78.0 * cosio2 + 137.0 * cosio4
        )
        argpdot = -0.5 * temp1 * con42 + 0.0625 * temp2 * (
            7.0 - 114.0 * cosio2 + 395.0 * cosio4
        ) + temp3 * (3.0 - 36.0 * cosio2 + 49.0 * cosio4)
        xhdot1 = -temp1 * cosio
        nodedot = xhdot1 + (
            0.5 * temp2 * (4.0 - 19.0 * cosio2)
            + 2.0 * temp3 * (3.0 - 7.0 * cosio2)
        ) * cosio
        xpidot = argpdot + nodedot
        omgcof = bstar * cc3 * math.cos(argpo)
        xmcof = -X2O3 * coef * bstar / eeta if (ecco > 1.0e-4 and abs(eeta) > 0.0) else 0.0
        nodecf = 3.5 * omeosq * xhdot1 * cc1
        t2cof = 1.5 * cc1
        if abs(cosio + 1.0) > TEMP4:
            xlcof = -0.25 * WGS72_J3OJ2 * sinio * (3.0 + 5.0 * cosio) / (1.0 + cosio)
        else:
            xlcof = -0.25 * WGS72_J3OJ2 * sinio * (3.0 + 5.0 * cosio) / TEMP4
        aycof = -0.5 * WGS72_J3OJ2 * sinio
        delmotemp = 1.0 + eta * math.cos(mo)
        delmo = delmotemp * delmotemp * delmotemp
        sinmao = math.sin(mo)
        x7thm1 = 7.0 * cosio2 - 1.0

        epoch = _deep_space_epoch_days(record.epoch_utc)
        jd, frac = datetime_to_julian_parts(record.epoch_utc)
        gsto = gmst_radians(jd, frac)
        deep_periodics = _dscom(epoch, ecco, argpo, 0.0, inclo, nodeo, no_unkozai)
        deep_resonance = _dsinit(
            cosim=deep_periodics["cosim"],
            emsq=deep_periodics["emsq"],
            argpo=argpo,
            dscom=deep_periodics,
            mo=mo,
            mdot=mdot,
            no_unkozai=no_unkozai,
            nodeo=nodeo,
            nodedot=nodedot,
            xpidot=xpidot,
            ecco=ecco,
            eccsq=eccsq,
            inclm=inclo,
            gsto=gsto,
        )

        _ = isimp
        return cls(
            record=record,
            ecco=ecco,
            inclo=inclo,
            nodeo=nodeo,
            argpo=argpo,
            mo=mo,
            bstar=bstar,
            no_unkozai=no_unkozai,
            con41=con41,
            x1mth2=x1mth2,
            x7thm1=x7thm1,
            cc1=cc1,
            cc4=cc4,
            cc5=cc5,
            mdot=mdot,
            argpdot=argpdot,
            nodedot=nodedot,
            omgcof=omgcof,
            xmcof=xmcof,
            nodecf=nodecf,
            t2cof=t2cof,
            xlcof=xlcof,
            aycof=aycof,
            delmo=delmo,
            sinmao=sinmao,
            deep_periodics=deep_periodics,
            deep_resonance=deep_resonance,
        )

    def propagate_minutes(self, tsince_minutes: float) -> TemeState:
        xmdf = self.mo + self.mdot * tsince_minutes
        argpdf = self.argpo + self.argpdot * tsince_minutes
        nodedf = self.nodeo + self.nodedot * tsince_minutes
        argpm = argpdf
        mm = xmdf
        t2 = tsince_minutes * tsince_minutes
        nodem = nodedf + self.nodecf * t2
        tempa = 1.0 - self.cc1 * tsince_minutes
        tempe = self.bstar * self.cc4 * tsince_minutes
        templ = self.t2cof * t2

        nm = self.no_unkozai
        em = self.ecco
        inclm = self.inclo

        deep = dict(self.deep_resonance)
        deep_state = _dspace(
            deep_terms=deep,
            t_minutes=tsince_minutes,
            tc_minutes=tsince_minutes,
            em=em,
            argpm=argpm,
            inclm=inclm,
            xli=float(deep["xli"]),
            mm=mm,
            xni=float(deep["xni"]),
            nodem=nodem,
            no_unkozai=self.no_unkozai,
            argpo=self.argpo,
            argpdot=self.argpdot,
        )
        em = deep_state["em"]
        argpm = deep_state["argpm"]
        inclm = deep_state["inclm"]
        mm = deep_state["mm"]
        nodem = deep_state["nodem"]
        nm = deep_state["nm"]

        if nm <= 0.0:
            raise RuntimeError("SGP4 propagation failed with code 2")

        am = math.pow(WGS72_XKE / nm, X2O3) * tempa * tempa
        nm = WGS72_XKE / math.pow(am, 1.5)
        em = em - tempe
        if em >= 1.0 or em < -0.001:
            raise RuntimeError("SGP4 propagation failed with code 1")
        if em < 1.0e-6:
            em = 1.0e-6

        mm = mm + self.no_unkozai * templ
        xlm = mm + argpm + nodem

        nodem = math.fmod(nodem, TWOPI)
        argpm = math.fmod(argpm, TWOPI)
        xlm = math.fmod(xlm, TWOPI)
        mm = math.fmod(xlm - argpm - nodem, TWOPI)

        ep = em
        xincp = inclm
        argpp = argpm
        nodep = nodem
        mp = mm
        ep, xincp, nodep, argpp, mp = _dpper(
            self.deep_periodics,
            tsince_minutes,
            self.inclo,
            "n",
            ep,
            xincp,
            nodep,
            argpp,
            mp,
        )
        if xincp < 0.0:
            xincp = -xincp
            nodep = nodep + math.pi
            argpp = argpp - math.pi
        if ep < 0.0 or ep > 1.0:
            raise RuntimeError("SGP4 propagation failed with code 3")

        sinip = math.sin(xincp)
        cosip = math.cos(xincp)
        aycof = -0.5 * WGS72_J3OJ2 * sinip
        if abs(cosip + 1.0) > TEMP4:
            xlcof = -0.25 * WGS72_J3OJ2 * sinip * (3.0 + 5.0 * cosip) / (1.0 + cosip)
        else:
            xlcof = -0.25 * WGS72_J3OJ2 * sinip * (3.0 + 5.0 * cosip) / TEMP4
        cosisq = cosip * cosip
        con41 = 3.0 * cosisq - 1.0
        x1mth2 = 1.0 - cosisq
        x7thm1 = 7.0 * cosisq - 1.0

        axnl = ep * math.cos(argpp)
        temp = 1.0 / (am * (1.0 - ep * ep))
        aynl = ep * math.sin(argpp) + temp * aycof
        xl = mp + argpp + nodep + temp * xlcof * axnl

        u = math.fmod(xl - nodep, TWOPI)
        eo1 = u
        delta = 9999.9
        ktr = 1
        while abs(delta) >= 1.0e-12 and ktr <= 10:
            sineo1 = math.sin(eo1)
            coseo1 = math.cos(eo1)
            denom = 1.0 - coseo1 * axnl - sineo1 * aynl
            delta = (u - aynl * coseo1 + axnl * sineo1 - eo1) / denom
            if abs(delta) >= 0.95:
                delta = 0.95 if delta > 0.0 else -0.95
            eo1 += delta
            ktr += 1

        sineo1 = math.sin(eo1)
        coseo1 = math.cos(eo1)
        ecose = axnl * coseo1 + aynl * sineo1
        esine = axnl * sineo1 - aynl * coseo1
        el2 = axnl * axnl + aynl * aynl
        pl = am * (1.0 - el2)
        if pl < 0.0:
            raise RuntimeError("SGP4 propagation failed with code 4")

        rl = am * (1.0 - ecose)
        rdotl = math.sqrt(am) * esine / rl
        rvdotl = math.sqrt(pl) / rl
        betal = math.sqrt(1.0 - el2)
        temp = esine / (1.0 + betal)
        sinu = am / rl * (sineo1 - aynl - axnl * temp)
        cosu = am / rl * (coseo1 - axnl + aynl * temp)
        su = math.atan2(sinu, cosu)
        sin2u = (cosu + cosu) * sinu
        cos2u = 1.0 - 2.0 * sinu * sinu
        temp = 1.0 / pl
        temp1 = 0.5 * WGS72_J2 * temp
        temp2 = temp1 * temp

        mrt = rl * (1.0 - 1.5 * temp2 * betal * con41) + 0.5 * temp1 * x1mth2 * cos2u
        su = su - 0.25 * temp2 * x7thm1 * sin2u
        xnode = nodep + 1.5 * temp2 * cosip * sin2u
        xinc = xincp + 1.5 * temp2 * cosip * sinip * cos2u
        mvt = rdotl - nm * temp1 * x1mth2 * sin2u / WGS72_XKE
        rvdot = rvdotl + nm * temp1 * (x1mth2 * cos2u + 1.5 * con41) / WGS72_XKE

        sinsu = math.sin(su)
        cossu = math.cos(su)
        snod = math.sin(xnode)
        cnod = math.cos(xnode)
        sini = math.sin(xinc)
        cosi = math.cos(xinc)
        xmx = -snod * cosi
        xmy = cnod * cosi
        ux = xmx * sinsu + cnod * cossu
        uy = xmy * sinsu + snod * cossu
        uz = sini * sinsu
        vx = xmx * cossu - cnod * sinsu
        vy = xmy * cossu - snod * sinsu
        vz = sini * cossu

        if mrt < 1.0:
            raise RuntimeError("SGP4 propagation failed with code 6")

        return TemeState(
            x_km=mrt * ux * WGS72_RADIUS_EARTH_KM,
            y_km=mrt * uy * WGS72_RADIUS_EARTH_KM,
            z_km=mrt * uz * WGS72_RADIUS_EARTH_KM,
            vx_km_s=(mvt * ux + rvdot * vx) * VKM_PER_SEC,
            vy_km_s=(mvt * uy + rvdot * vy) * VKM_PER_SEC,
            vz_km_s=(mvt * uz + rvdot * vz) * VKM_PER_SEC,
        )
