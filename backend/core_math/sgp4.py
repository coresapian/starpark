"""Pure Python SGP4 propagation entrypoints for LinkSpot.

This module implements the near-Earth SGP4 branch directly and dispatches to
the in-repo deep-space branch when the orbital period requires SDP4 handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .time import ensure_utc
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


@dataclass
class NearEarthSgp4Propagator:
    """State container for the near-Earth SGP4 branch."""

    record: TleRecord
    no_kozai: float
    ecco: float
    inclo: float
    nodeo: float
    argpo: float
    mo: float
    bstar: float
    no_unkozai: float
    ao: float
    con41: float
    cosio: float
    cosio2: float
    omeosq: float
    sinio: float
    rp: float
    isimp: int
    eta: float
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
    x1mth2: float
    x7thm1: float
    d2: float
    d3: float
    d4: float
    t3cof: float
    t4cof: float
    t5cof: float

    @classmethod
    def from_tle(cls, record: TleRecord) -> NearEarthSgp4Propagator:
        """Initialize a near-Earth SGP4 state from a TLE record."""
        no_kozai = float(record.mean_motion_rev_per_day) * TWOPI / 1440.0
        ecco = float(record.eccentricity)
        inclo = math.radians(record.inclination_deg)
        nodeo = math.radians(record.raan_deg)
        argpo = math.radians(record.argument_of_perigee_deg)
        mo = math.radians(record.mean_anomaly_deg)
        bstar = float(record.bstar)

        if no_kozai <= 0.0:
            raise ValueError("Mean motion must be positive")

        eccsq = ecco * ecco
        omeosq = 1.0 - eccsq
        rteosq = math.sqrt(omeosq)
        cosio = math.cos(inclo)
        cosio2 = cosio * cosio

        ak = math.pow(WGS72_XKE / no_kozai, X2O3)
        d1 = 0.75 * WGS72_J2 * (3.0 * cosio2 - 1.0) / (rteosq * omeosq)
        del1 = d1 / (ak * ak)
        adel = ak * (
            1.0
            - del1 * del1
            - del1 * (1.0 / 3.0 + 134.0 * del1 * del1 / 81.0)
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

        orbital_period_minutes = TWOPI / no_unkozai
        if orbital_period_minutes >= 225.0:
            raise NotImplementedError(
                "Deep-space SGP4 branch is not implemented in LinkSpot core yet"
            )

        isimp = 1 if rp < (220.0 / WGS72_RADIUS_EARTH_KM + 1.0) else 0
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
            cc3 = (
                -2.0
                * coef
                * tsi
                * WGS72_J3OJ2
                * no_unkozai
                * sinio
                / ecco
            )
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
        omgcof = bstar * cc3 * math.cos(argpo)
        xmcof = 0.0
        if abs(eeta) > 0.0 and ecco > 1.0e-4:
            xmcof = -X2O3 * coef * bstar / eeta
        nodecf = 3.5 * omeosq * xhdot1 * cc1
        t2cof = 1.5 * cc1
        if abs(cosio + 1.0) > TEMP4:
            xlcof = (
                -0.25
                * WGS72_J3OJ2
                * sinio
                * (3.0 + 5.0 * cosio)
                / (1.0 + cosio)
            )
        else:
            xlcof = (
                -0.25
                * WGS72_J3OJ2
                * sinio
                * (3.0 + 5.0 * cosio)
                / TEMP4
            )
        aycof = -0.5 * WGS72_J3OJ2 * sinio
        delmotemp = 1.0 + eta * math.cos(mo)
        delmo = delmotemp * delmotemp * delmotemp
        sinmao = math.sin(mo)
        x7thm1 = 7.0 * cosio2 - 1.0

        d2 = 0.0
        d3 = 0.0
        d4 = 0.0
        t3cof = 0.0
        t4cof = 0.0
        t5cof = 0.0
        if isimp != 1:
            cc1sq = cc1 * cc1
            d2 = 4.0 * ao * tsi * cc1sq
            temp = d2 * tsi * cc1 / 3.0
            d3 = (17.0 * ao + sfour) * temp
            d4 = 0.5 * temp * ao * tsi * (221.0 * ao + 31.0 * sfour) * cc1
            t3cof = d2 + 2.0 * cc1sq
            t4cof = 0.25 * (3.0 * d3 + cc1 * (12.0 * d2 + 10.0 * cc1sq))
            t5cof = 0.2 * (
                3.0 * d4
                + 12.0 * cc1 * d3
                + 6.0 * d2 * d2
                + 15.0 * cc1sq * (2.0 * d2 + cc1sq)
            )

        return cls(
            record=record,
            no_kozai=no_kozai,
            ecco=ecco,
            inclo=inclo,
            nodeo=nodeo,
            argpo=argpo,
            mo=mo,
            bstar=bstar,
            no_unkozai=no_unkozai,
            ao=ao,
            con41=con41,
            cosio=cosio,
            cosio2=cosio2,
            omeosq=omeosq,
            sinio=sinio,
            rp=rp,
            isimp=isimp,
            eta=eta,
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
            x1mth2=x1mth2,
            x7thm1=x7thm1,
            d2=d2,
            d3=d3,
            d4=d4,
            t3cof=t3cof,
            t4cof=t4cof,
            t5cof=t5cof,
        )

    def propagate_minutes(self, tsince_minutes: float) -> TemeState:
        """Propagate to TEME position/velocity at `tsince_minutes` since epoch."""
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

        if self.isimp != 1:
            delomg = self.omgcof * tsince_minutes
            delmtemp = 1.0 + self.eta * math.cos(xmdf)
            delm = self.xmcof * (delmtemp * delmtemp * delmtemp - self.delmo)
            temp = delomg + delm
            mm = xmdf + temp
            argpm = argpdf - temp
            t3 = t2 * tsince_minutes
            t4 = t3 * tsince_minutes
            tempa = tempa - self.d2 * t2 - self.d3 * t3 - self.d4 * t4
            tempe = tempe + self.bstar * self.cc5 * (math.sin(mm) - self.sinmao)
            templ = templ + self.t3cof * t3 + t4 * (
                self.t4cof + tsince_minutes * self.t5cof
            )

        nm = self.no_unkozai
        em = self.ecco
        inclm = self.inclo

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

        sinim = math.sin(inclm)
        cosim = math.cos(inclm)
        ep = em
        xincp = inclm
        argpp = argpm
        nodep = nodem
        mp = mm

        axnl = ep * math.cos(argpp)
        temp = 1.0 / (am * (1.0 - ep * ep))
        aynl = ep * math.sin(argpp) + temp * self.aycof
        xl = mp + argpp + nodep + temp * self.xlcof * axnl

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

        mrt = rl * (1.0 - 1.5 * temp2 * betal * self.con41) + 0.5 * temp1 * self.x1mth2 * cos2u
        su = su - 0.25 * temp2 * self.x7thm1 * sin2u
        xnode = nodep + 1.5 * temp2 * cosim * sin2u
        xinc = xincp + 1.5 * temp2 * cosim * sinim * cos2u
        mvt = rdotl - nm * temp1 * self.x1mth2 * sin2u / WGS72_XKE
        rvdot = rvdotl + nm * temp1 * (self.x1mth2 * cos2u + 1.5 * self.con41) / WGS72_XKE

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


def propagate_tle_teme(record: TleRecord, when_utc: datetime) -> TemeState:
    """Propagate a TLE into TEME coordinates with in-repo SGP4/SDP4 logic."""
    try:
        propagator = NearEarthSgp4Propagator.from_tle(record)
    except NotImplementedError:
        from .sgp4_deep_space import DeepSpaceSgp4Propagator

        propagator = DeepSpaceSgp4Propagator.from_tle(record)
    delta_minutes = (
        ensure_utc(when_utc) - ensure_utc(record.epoch_utc)
    ).total_seconds() / 60.0
    return propagator.propagate_minutes(delta_minutes)
