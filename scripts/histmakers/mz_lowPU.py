import argparse
from utilities import output_tools, differential
from utilities import common, logging

parser,initargs = common.common_parser()
parser.add_argument("--flavor", type=str, choices=["ee", "mumu"], help="Flavor (ee or mumu)", default="mumu")

parser = common.set_parser_default(parser, "genVars", ["ptVGen"])
parser = common.set_parser_default(parser, "pt", [34, 26, 60])
parser = common.set_parser_default(parser, "aggregateGroups", ["Diboson", "Top", "Wtaunu", "Wmunu", "Wenu"])

args = parser.parse_args()
logger = logging.setup_logger(__file__, args.verbose, args.noColorLogger)

import narf
import wremnants
from wremnants import theory_tools, syst_tools, theory_corrections, muon_selections, unfolding_tools
from wremnants.histmaker_tools import scale_to_data, aggregate_groups
import hist
import scripts.lowPU.config as lowPUcfg


corr_helpers = theory_corrections.load_corr_helpers(common.vprocs_lowpu, args.theoryCorr)

###################################
flavor = args.flavor # mumu, ee
sigProcs = ["Zmumu"] if flavor == "mumu" else ["Zee"]
base_group = sigProcs[0]

# dilepton invariant mass cuts
mass_min = 60
mass_max = 120
# transverse boson mass cut
mtw_min=45 # 40 for Wmass, thus be 45 here (roughly half the boson mass)

datasets = wremnants.datasetsLowPU.getDatasets(maxFiles=args.maxFiles,
                                              filt=args.filterProcs,
                                              excl=args.excludeProcs, 
                                              flavor=flavor)


for d in datasets: logger.info(f"Dataset {d.name}")


# load lowPU specific libs
#ROOT.gInterpreter.AddIncludePath(f"{pathlib.Path(__file__).parent}/include/")
narf.clingutils.Declare('#include "lowpu_utils.h"')
narf.clingutils.Declare('#include "lowpu_efficiencies.h"')
narf.clingutils.Declare('#include "lowpu_prefire.h"')
narf.clingutils.Declare('#include "lowpu_rochester.h"')
narf.clingutils.Declare('#include "lowpu_recoil.h"')
narf.clingutils.Declare('#include "electron_selections.h"')


# standard regular axes
axis_eta = hist.axis.Regular(48, -2.4, 2.4, name = "eta")
axis_pt = hist.axis.Regular(29, 26., 55., name = "pt")
axis_charge = hist.axis.Regular(2, -2., 2., underflow=False, overflow=False, name = "charge")
#axis_mll = hist.axis.Regular(60, 60., 120., underflow=False, overflow=False, name = "mll")
axis_yll = hist.axis.Regular(50, -2.5, 2.5, name = "yll")
axis_ptll = hist.axis.Regular(300, 0, 300,  name = "ptll")

axis_ptl = hist.axis.Regular(100, 0., 200., name = "ptl")
axis_etal = hist.axis.Regular(50, -2.5, 2.5, name = "etal")


bins_mll = [60, 65, 70, 72, 74, 76, 78] + list(range(80, 100, 1)) + [100, 102, 104, 106, 108, 110, 115, 120]
axis_mll = hist.axis.Variable(bins_mll, name = "mll") 
axis_lin = hist.axis.Regular(5, 0, 5, name = "lin")

qcdScaleByHelicity_helper = wremnants.makeQCDScaleByHelicityHelper(is_w_like = True)
axis_ptVgen = qcdScaleByHelicity_helper.hist.axes["ptVgen"]
axis_chargeVgen = qcdScaleByHelicity_helper.hist.axes["chargeVgen"]

gen_axes = {
    "ptVGen": hist.axis.Variable([0, 8, 14, 20, 30, 40, 50, 60, 75, 90, 150], name = "ptVGen", underflow=False, overflow=False),
    "absYVGen": hist.axis.Regular(10, 0, 2.5, name = "absYVGen", underflow=False, overflow=False),  
}

if args.unfolding:
    unfolding_axes, unfolding_cols, unfolding_selections = differential.get_dilepton_axes(args.genVars, gen_axes)
    datasets = unfolding_tools.add_out_of_acceptance(datasets, group = base_group)
    
# axes for final cards/fitting
nominal_axes = [
    hist.axis.Variable([0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 25, 30, 40, 50, 60, 75, 90, 150], name = "ptll", underflow=False, overflow=True),
    hist.axis.Regular(20, -2.5, 2.5, name = "yll", overflow=True, underflow=True), 
    axis_charge]

# corresponding columns
nominal_cols = ["ptll", "yll", "TrigMuon_charge"]

axis_mt = hist.axis.Regular(200, 0., 200., name = "mt", underflow=False)
axes_mT = [axis_mt]
cols_mT = ["transverseMass"]

# recoil initialization
if not args.noRecoil:
    from wremnants import recoil_tools
    recoilHelper = recoil_tools.Recoil("lowPU", args, flavor)


def build_graph(df, dataset):
    logger.info(f"build graph for dataset: {dataset.name}")

    results = []

    isW = dataset.name in common.wprocs_lowpu
    isZ = dataset.name in common.zprocs_lowpu

    if dataset.is_data: df = df.DefinePerSample("weight", "1.0")
    else: df = df.Define("weight", "std::copysign(1.0, genWeight)")
  
    weightsum = df.SumAndCount("weight")

    axes = nominal_axes
    cols = nominal_cols

    if args.unfolding and dataset.name in sigProcs:
        df = unfolding_tools.define_gen_level(df, args.genLevel, dataset.name, mode="wlike")

        if hasattr(dataset, "out_of_acceptance"):
            logger.debug("Reject events in fiducial phase space")
            df = unfolding_tools.select_fiducial_space(df, mode="wlike", pt_min=args.pt[1], pt_max=args.pt[2], 
                mass_min=mass_min, mass_max=mass_max, mtw_min=0, selections=unfolding_selections, accept=False)
        else:
            logger.debug("Select events in fiducial phase space")
            df = unfolding_tools.select_fiducial_space(df, mode="wlike", pt_min=args.pt[1], pt_max=args.pt[2], 
                mass_min=mass_min, mass_max=mass_max, mtw_min=0, selections=unfolding_selections, accept=True)

            unfolding_tools.add_xnorm_histograms(results, df, args, dataset.name, corr_helpers, qcdScaleByHelicity_helper, unfolding_axes, unfolding_cols)
            axes = [*axes, *unfolding_axes] 
            cols = [*cols, *unfolding_cols]

    df = df.Define("TrigMuon_charge", "event % 2 == 0 ? -1 : 1") # wlike charge
 
    if flavor == "mumu":
    
        if not dataset.is_data: 
        
            df = df.Define("Muon_pt_corr", "wrem::applyRochesterMC(Muon_pt, Muon_eta, Muon_phi, Muon_charge, Muon_genPartIdx, GenPart_pt, Muon_nTrackerLayers)")
            #df = df.Alias("Muon_pt_corr", "Muon_pt")
            df = df.Filter("HLT_Mu17")
            
        else: 
        
            df = df.Define("Muon_pt_corr", "wrem::applyRochesterData(Muon_pt, Muon_eta, Muon_phi, Muon_charge)")
            #df = df.Alias("Muon_pt_corr", "Muon_pt")
            df = df.Filter("HLT_HIMu17")
            
        
        df = df.Define("vetoMuons", "Muon_pt_corr > 10 && Muon_looseId && abs(Muon_eta) < 2.4 && abs(Muon_dxybs) < 0.05")
        df = df.Filter("Sum(vetoMuons) == 2")
        
        df = df.Define("vetoElectrons", "Electron_pt > 10 && Electron_cutBased > 0 && abs(Electron_eta) < 2.4")
        df = df.Filter("Sum(vetoElectrons) == 0")

        df = df.Define("goodLeptons", f"vetoMuons && Muon_pt_corr > {args.pt[1]} && Muon_mediumId && Muon_pfRelIso04_all < 0.15")
        df = df.Define("goodLeptonsPlus", "goodLeptons && Muon_charge > 0")
        df = df.Define("goodLeptonsMinus", "goodLeptons && Muon_charge < 0")
        df = df.Filter("Sum(goodLeptons) == 2")
        df = df.Filter("(Muon_charge[goodLeptons][0] + Muon_charge[goodLeptons][1]) == 0")
        
        df = df.Define("goodTrigObjs", "wrem::goodMuonTriggerCandidateLowPU(TrigObj_id, TrigObj_pt, TrigObj_l1pt, TrigObj_l2pt, TrigObj_filterBits)")
        df = df.Define("trigMatch", "wrem::hasTriggerMatchLowPU(Muon_eta[goodLeptons], Muon_phi[goodLeptons], TrigObj_eta[goodTrigObjs], TrigObj_phi[goodTrigObjs])")
        df = df.Define("nonTrigMatch", "wrem::inverse(trigMatch)")
        df = df.Filter("Sum(trigMatch) > 0")

        df = df.Define("Lep_pt_uncorr", "Muon_pt[goodLeptons]")
        df = df.Define("Lep_pt", "Muon_pt_corr[goodLeptons]")
        df = df.Define("Lep_eta", "Muon_eta[goodLeptons]")
        df = df.Define("Lep_phi", "Muon_phi[goodLeptons]")
        df = df.Define("Lep_charge", "Muon_charge[goodLeptons]")
        df = df.Define("Lep_mass", "Muon_mass[goodLeptons]")
        
        if not dataset.is_data:
            df = df.Define("lepSF_ISO", "wrem::lepSF(Muon_pt_corr[goodLeptons], Muon_eta[goodLeptons], Muon_charge[goodLeptons], 1)")
            df = df.Define("lepSF_IDIP", "wrem::lepSF(Muon_pt_corr[goodLeptons], Muon_eta[goodLeptons], Muon_charge[goodLeptons], 2)") # largest effect
            df = df.Define("lepSF_HLT", "wrem::lepSF_HLT_q(Muon_pt_corr[goodLeptons], Muon_eta[goodLeptons], Muon_charge[goodLeptons], 13)")
            df = df.Define("prefireCorr", "wrem::prefireCorr(0, Jet_pt, Jet_eta, Jet_phi, Jet_muEF, Jet_neEmEF, Jet_chEmEF, Photon_pt, Photon_eta, Photon_phi, Muon_pt_corr[goodLeptons], Muon_eta[goodLeptons], Muon_phi[goodLeptons])")
            df = df.Define("SFMC", "lepSF_IDIP*lepSF_ISO*lepSF_HLT*prefireCorr")
        
        else: df = df.Define("SFMC", "1.0")
    
    else:
    
        # undo the scale/smearing corrections, needed to correct RawMET
        df = df.Define("Lep_pt_uncorr", "wrem::Egamma_undoCorrection(Electron_pt, Electron_eta, Electron_ecalCorr)")

        if not dataset.is_data: 
            
            df = df.Define("Electron_pt_corr", "wrem::applyEGammaScaleSmearingUnc(0, Electron_pt, Electron_eta, Electron_dEscaleUp, Electron_dEscaleDown, Electron_dEsigmaUp, Electron_dEsigmaDown, 1)")
            df = df.Filter("HLT_Ele20_WPLoose_Gsf")
            
        else: 
            df = df.Define("Electron_pt_corr", "wrem::applyEGammaScaleSmearingUnc(1, Electron_pt, Electron_eta, Electron_dEscaleUp, Electron_dEscaleDown, Electron_dEsigmaUp, Electron_dEsigmaDown, 1)")
            df = df.Filter("HLT_HIEle20_WPLoose_Gsf")
            
            
        df = df.Define("vetoElectrons", "Electron_pt_corr > 10 && Electron_cutBased > 0 && abs(Electron_eta) < 2.4")
        df = df.Filter("Sum(vetoElectrons)==2")
        
        df = df.Define("vetoMuons", "Muon_pt > 10 && Muon_looseId && abs(Muon_eta) < 2.4 && abs(Muon_dxybs) < 0.05 && abs(Muon_dz)< 0.2")
        df = df.Filter("Sum(vetoMuons) == 0")

        df = df.Define("Electron_MediumID", "wrem::electron_id::pass_cutbased<3>(Electron_vidNestedWPBitmap)")
        df = df.Define("goodLeptons", "Electron_MediumID > 0")
        df = df.Filter("Sum(goodLeptons)==2")

        df = df.Define("goodLeptonsPlus", "goodLeptons && Electron_charge > 0")
        df = df.Define("goodLeptonsMinus", "goodLeptons && Electron_charge < 0")
        
        df = df.Filter("(Electron_charge[goodLeptons][0] + Electron_charge[goodLeptons][1]) == 0")
        df = df.Define("goodTrigObjs", "wrem::goodElectronTriggerCandidateLowPU(TrigObj_id, TrigObj_pt, TrigObj_l1pt, TrigObj_l2pt, TrigObj_filterBits)")
        df = df.Define("trigMatch", "wrem::hasTriggerMatchLowPU(Electron_eta[goodLeptons], Electron_phi[goodLeptons], TrigObj_eta[goodTrigObjs], TrigObj_phi[goodTrigObjs])")
        df = df.Define("nonTrigMatch", "wrem::inverse(trigMatch)")
        df = df.Filter("Sum(trigMatch) > 0")
        
        #df = df.Define("Lep_pt_uncorr", "Electron_pt[goodLeptons]")
        df = df.Define("Lep_pt", "Electron_pt_corr[goodLeptons]")
        df = df.Define("Lep_eta", "Electron_eta[goodLeptons]")
        df = df.Define("Lep_phi", "Electron_phi[goodLeptons]")
        df = df.Define("Lep_charge", "Electron_charge[goodLeptons]")
        df = df.Define("Lep_mass", "Electron_mass[goodLeptons]")
        
        if not dataset.is_data:
            df = df.Define("lepSF_IDISO", "wrem::lepSF(Electron_pt_corr[goodLeptons], Electron_eta[goodLeptons], Electron_charge[goodLeptons], 3)")
            df = df.Define("lepSF_HLT", "wrem::lepSF_HLT_q(Electron_pt_corr[goodLeptons], Electron_eta[goodLeptons], Electron_charge[goodLeptons], 11)")
            df = df.Define("prefireCorr", "wrem::prefireCorr(0, Jet_pt, Jet_eta, Jet_phi, Jet_muEF, Jet_neEmEF, Jet_chEmEF, Photon_pt, Photon_eta, Photon_phi, Electron_pt_corr[goodLeptons], Electron_eta[goodLeptons], Electron_phi[goodLeptons])")
            df = df.Define("SFMC", "lepSF_IDISO*lepSF_HLT*prefireCorr")
        
        else: df = df.Define("SFMC", "1.0")    
    
    df = df.Filter(f"Lep_pt[0] > {args.pt[1]} & Lep_pt[0] < {args.pt[2]}")
    df = df.Filter(f"Lep_pt[1] > {args.pt[1]} & Lep_pt[1] < {args.pt[2]}")
        
    df = muon_selections.apply_met_filters(df)

    df = df.Define("Lep1_mom4", "ROOT::Math::PtEtaPhiMVector(Lep_pt[0], Lep_eta[0], Lep_phi[0], Lep_mass[0])")
    df = df.Define("Lep2_mom4", "ROOT::Math::PtEtaPhiMVector(Lep_pt[1], Lep_eta[1], Lep_phi[1], Lep_mass[0])")
    df = df.Define("ll_mom4", "ROOT::Math::PxPyPzEVector(Lep1_mom4) + ROOT::Math::PxPyPzEVector(Lep2_mom4)")
    df = df.Define("mll", "ll_mom4.mass()")
    df = df.Filter(f"mll > {mass_min} && mll < {mass_max}")

    df = df.Define("ptll", "ll_mom4.pt()")
    df = df.Define("yll", "ll_mom4.Rapidity()")
    df = df.Define("absYll", "std::fabs(yll)")


    if not dataset.is_data:
        df = df.Define("exp_weight", "SFMC")
        df = theory_tools.define_theory_weights_and_corrs(df, dataset.name, corr_helpers, args)
    else:
        df = df.DefinePerSample("nominal_weight", "1.0")

    # lepton kinematics: leading/subleading, triggered/nontriggered
    df = df.Define("Lep_pt_leading", "Lep_pt[0] > Lep_pt[1] ? Lep_pt[0] : Lep_pt[1]")
    df = df.Define("Lep_pt_subleading", "Lep_pt[0] > Lep_pt[1] ? Lep_pt[1] : Lep_pt[0]")
    df = df.Define("Lep_pt_plus", "Lep_charge[0] > 0 ? Lep_pt[0] : Lep_pt[1]")
    df = df.Define("Lep_pt_minus", "Lep_charge[0] > 0? Lep_pt[1] : Lep_pt[0]")
    df = df.Define("Lep_pt_trg", "Lep_pt[trigMatch]")    
    df = df.Define("Lep_pt_nontrg", "Lep_pt[nonTrigMatch]")
    
    df = df.Define("Lep_eta_leading", "Lep_pt[0] > Lep_pt[1] ? Lep_eta[0] : Lep_eta[1]")
    df = df.Define("Lep_eta_subleading", "Lep_pt[0] > Lep_pt[1] ? Lep_eta[1] : Lep_eta[0]")
    df = df.Define("Lep_eta_plus", "Lep_charge[0] > 0 ? Lep_eta[0] : Lep_eta[1]")
    df = df.Define("Lep_eta_minus", "Lep_charge[0] > 0? Lep_eta[1] : Lep_eta[0]")
    df = df.Define("Lep_eta_trg", "Lep_eta[trigMatch]")
    df = df.Define("Lep_eta_nontrg", "Lep_eta[nonTrigMatch]")
    
    results.append(df.HistoBoost("lep_pt", [axis_ptl], ["Lep_pt", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pt_leading", [axis_ptl], ["Lep_pt_leading", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pt_subleading", [axis_ptl], ["Lep_pt_subleading", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pt_plus", [axis_ptl], ["Lep_pt_plus", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pt_minus", [axis_ptl], ["Lep_pt_minus", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pt_trg", [axis_ptl], ["Lep_pt_trg", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pt_nontrg", [axis_ptl], ["Lep_pt_nontrg", "nominal_weight"]))

    results.append(df.HistoBoost("lep_eta", [axis_etal], ["Lep_eta", "nominal_weight"]))
    results.append(df.HistoBoost("lep_eta_leading", [axis_etal], ["Lep_eta_leading", "nominal_weight"]))
    results.append(df.HistoBoost("lep_eta_subleading", [axis_etal], ["Lep_eta_subleading", "nominal_weight"]))
    results.append(df.HistoBoost("lep_eta_plus", [axis_etal], ["Lep_eta_plus", "nominal_weight"]))
    results.append(df.HistoBoost("lep_eta_minus", [axis_etal], ["Lep_eta_minus", "nominal_weight"]))
    results.append(df.HistoBoost("lep_eta_trg", [axis_etal], ["Lep_eta_trg", "nominal_weight"]))
    results.append(df.HistoBoost("lep_eta_nontrg", [axis_etal], ["Lep_eta_nontrg", "nominal_weight"]))

    df = df.Define("noTrigMatch", "Sum(trigMatch)")
    results.append(df.HistoBoost("noTrigMatch", [axis_lin], ["noTrigMatch", "nominal_weight"]))

    
    # W-like
    #df = df.Define("TrigMuon_charge", "event % 2 == 0 ? -1 : 1")
    df = df.Define("NonTrigMuon_charge", "-TrigMuon_charge")
    df = df.Define("trigMuons", "Lep_charge == TrigMuon_charge")
    df = df.Define("nonTrigMuons", "Lep_charge == NonTrigMuon_charge")
    df = df.Define("TrigMuon_pt", "Lep_pt[trigMuons][0]")
    df = df.Define("TrigMuon_eta", "Lep_eta[trigMuons][0]")
    df = df.Define("TrigMuon_phi", "Lep_phi[trigMuons][0]")

    df = df.Define("NonTrigMuon_pt", "Lep_pt[nonTrigMuons][0]")
    df = df.Define("NonTrigMuon_eta", "Lep_eta[nonTrigMuons][0]")
    df = df.Define("NonTrigMuon_phi", "Lep_phi[nonTrigMuons][0]")

    # Recoil calibrations
    if not args.noRecoil:
        lep_cols = ["Lep_pt", "Lep_phi", "Lep_pt_uncorr"]
        trg_cols = ["TrigMuon_pt", "TrigMuon_phi", "NonTrigMuon_pt", "NonTrigMuon_phi"]
        df = recoilHelper.recoil_Z(df, results, dataset, common.zprocs_recoil_lowpu, lep_cols, trg_cols) # produces corrected MET as MET_corr_rec_pt/phi
    else:
        df = df.Alias("MET_corr_rec_pt", "MET_pt")
        df = df.Alias("MET_corr_rec_phi", "MET_phi")
        df = df.Alias("nominal_weight_qTrw", "nominal_weight")

    results.append(df.HistoBoost("mll", [axis_mll], ["mll", "nominal_weight"]))
    results.append(df.HistoBoost("yll", [axis_yll], ["yll", "nominal_weight"]))
    results.append(df.HistoBoost("ptll", [axis_ptll], ["ptll", "nominal_weight"]))
    
    df = df.Define("transverseMass", f"wrem::get_mt_wlike(TrigMuon_pt, TrigMuon_phi, NonTrigMuon_pt, NonTrigMuon_phi, MET_corr_rec_pt, MET_corr_rec_phi)")
    results.append(df.HistoBoost("transverseMass", axes_mT, [*cols_mT, "nominal_weight"]))
    
    if mtw_min > 0:
        df = df.Filter(f"transverseMass >= {mtw_min}")

    results.append(df.HistoBoost("lep_pT", [axis_pt], ["TrigMuon_pt", "nominal_weight"]))
    results.append(df.HistoBoost("lep_pT_qTrw", [axis_pt], ["TrigMuon_pt", "nominal_weight_qTrw"]))
        
    if dataset.name in common.vprocs_lowpu:
        df = syst_tools.add_theory_hists(results, df, args, dataset.name, corr_helpers, qcdScaleByHelicity_helper, axes, cols, for_wmass=False)
        df = syst_tools.add_theory_hists(results, df, args, dataset.name, corr_helpers, qcdScaleByHelicity_helper, axes_mT, cols_mT, base_name="transverseMass", for_wmass=False)

    results.append(df.HistoBoost("nominal", axes, [*cols, "nominal_weight"]))

    df = lowPUcfg.lepSF_systs(df, results, "lepSF_HLT_DATA_stat", 120, "wrem::lepSF_HLT_var_mu(1, Lep_pt, Lep_eta, Lep_charge)", "nominal",  axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_HLT_DATA_syst", 120, "wrem::lepSF_HLT_var_mu(2, Lep_pt, Lep_eta, Lep_charge)", "nominal",  axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_HLT_MC_stat",   120, "wrem::lepSF_HLT_var_mu(-1, Lep_pt, Lep_eta, Lep_charge)", "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_HLT_MC_syst",   120, "wrem::lepSF_HLT_var_mu(-2, Lep_pt, Lep_eta, Lep_charge)", "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_ISO_stat",      36,  "wrem::lepSF_ISO_var_mu(1, Lep_pt, Lep_eta, Lep_charge)",  "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_ISO_DATA_syst", 36,  "wrem::lepSF_ISO_var_mu(2, Lep_pt, Lep_eta, Lep_charge)",  "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_ISO_MC_syst",   36,  "wrem::lepSF_ISO_var_mu(-2, Lep_pt, Lep_eta, Lep_charge)", "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_IDIP_stat",     36,  "wrem::lepSF_IDIP_var_mu(1, Lep_pt, Lep_eta, Lep_charge)",  "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_IDIP_DATA_syst",36,  "wrem::lepSF_IDIP_var_mu(2, Lep_pt, Lep_eta, Lep_charge)",  "nominal", axes, cols)
    df = lowPUcfg.lepSF_systs(df, results, "lepSF_IDIP_MC_syst",  36,  "wrem::lepSF_IDIP_var_mu(-2, Lep_pt, Lep_eta, Lep_charge)", "nominal", axes, cols)

    # prefire
    df = df.Define("prefireCorr_syst", "wrem::prefireCorr_syst(Jet_pt, Jet_eta, Jet_phi, Jet_muEF, Jet_neEmEF, Jet_chEmEF, Photon_pt, Photon_eta, Photon_phi, Lep_pt, Lep_eta, Lep_phi)")
    df = df.Define("prefireCorr_syst_tensor", "Eigen::TensorFixedSize<double, Eigen::Sizes<2>> res; auto w = nominal_weight*prefireCorr_syst; std::copy(std::begin(w), std::end(w), res.data()); return res;")
    results.append(df.HistoBoost("nominal_prefireCorr", [*axes], [*cols, "prefireCorr_syst_tensor"], tensor_axes = [common.down_up_axis]))

    if dataset.name in sigProcs:

        # mass weights (Breit-Wigner and nominal)
        df = syst_tools.define_mass_weights(df, dataset.name)
        syst_tools.add_massweights_hist(results, df, axes, [*cols], base_name="nominal", proc=dataset.name)
        syst_tools.add_massweights_hist(results, df, axes_mT, cols_mT, base_name="transverseMass", proc=dataset.name)   
        syst_tools.add_massweights_hist(results, df, [common.axis_mll_lowpu], ["mll"], base_name="mll_massWeight", proc=dataset.name)

    if not dataset.is_data and not args.onlyMainHistograms:
        if not args.noRecoil:
            df = recoilHelper.add_recoil_unc_W(df, results, dataset, cols, axes, "nominal")
            

    if hasattr(dataset, "out_of_acceptance"):
        # Rename dataset to not overwrite the original one
        dataset.name = "Bkg"+dataset.name

    return results, weightsum

resultdict = narf.build_and_run(datasets, build_graph)

if not args.noScaleToData:
    scale_to_data(resultdict)
    aggregate_groups(datasets, resultdict, args.aggregateGroups)

output_tools.write_analysis_output(resultdict, f"mz_lowPU_{flavor}.hdf5", args, update_name=not args.forceDefaultName)
